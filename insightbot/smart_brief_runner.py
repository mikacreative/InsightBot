import json
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional

import feedparser
import requests

from .ai import chat_completion
from .wecom import send_markdown_to_app

# ---------- constants ----------
MAX_ITEMS_PER_BATCH = 15   # 每批交给 AI 的新闻条数
MAX_RETRIES = 3
RETRY_DELAY_S = 5
FEED_FETCH_TIMEOUT_S = 15
DEBUG_SAMPLE_NEWS = [
    {"title": "[RSS] 微信视频号广告 ROI 提升 30%，品牌主加速布局", "link": "https://example.com/001"},
    {"title": "[RSS] 小红书推出品牌号新功能：支持直链跳转电商平台", "link": "https://example.com/002"},
    {"title": "[RSS] AI 文案工具月活突破 500 万，营销效率提升显著", "link": "https://example.com/003"},
    {"title": "[RSS] 某明星离婚八卦新闻（无关内容，测试拦截）", "link": "https://example.com/004"},
    {"title": "[RSS] 抖音电商 GMV 同比增长 45%，直播带货进入精细化运营阶段", "link": "https://example.com/005"},
]

# 简化的 system prompt（格式规则全部由代码处理，AI 只负责判断和提炼）
DEFAULT_SYSTEM_PROMPT = """你是一个拥有 10 年经验的资深营销情报官。
你的任务：从新闻列表中，挑选出与中国市场营销、公关传播最具参考价值的资讯，每条输出一句话影响点评。

【行业聚焦】
优先关注：生活方式、运动、时尚、地产、酒店、消费品牌等行业动态。
剔除：低价值通稿、自媒体八卦、人事变动、娱乐新闻、算法学术论文、与营销无关的纯技术内容。"""
# --------------------------------


def _render_markdown(category: str, items: List[dict]) -> str:
    """将结构化 items 渲染为 Markdown 格式"""
    blocks = [f"## {category}\n"]
    for item in items:
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        summary = item.get("summary", "").strip()
        # 防御：url 为空时跳过该条
        if not url:
            continue
        blocks.append(f"### [{title}]({url})\n")
        blocks.append(f"> 💡 *{summary}*\n\n")
    return "".join(blocks).strip()


def _build_system_prompt(base_system_prompt: str, category_prompt: str = "") -> str:
    system_prompt = (base_system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    system_prompt += """

【输出格式】
你必须返回 JSON 对象，不要返回任何其他内容：
{
  "items": [
    {
      "title": "重写后的简体中文标题（必须去除'震惊''重磅''突发'等虚假修饰词；结构：[主体] + [核心动作]；不超过50字）",
      "url": "原文链接（必须保留，不可省略）",
      "summary": "一句话摘要（30字以内，简体中文，平实老练，指出对营销人的具体启示）"
    }
  ]
}

【关键规则】
- 宁缺毋滥：若列表中没有任何符合标准的新闻，返回 {"items": []}
- url 必须为有效链接，不可为空，不可省略
- 摘要必须使用简体中文
- 不要输出任何解释、说明或开场白，只输出 JSON"""
    if category_prompt:
        system_prompt += f"\n\n【本板块额外筛选标准】：\n{category_prompt}"
    return system_prompt


def _parse_feed_url(url: str):
    response = requests.get(
        url,
        timeout=FEED_FETCH_TIMEOUT_S,
        headers={"User-Agent": "InsightBot/0.3.0 (+https://github.com/mikacreative/InsightBot)"},
    )
    response.raise_for_status()
    return feedparser.parse(response.content)


def _build_candidate_lines(news_list: List[dict]) -> List[str]:
    lines = []
    for i, news in enumerate(news_list):
        clean_title = str(news.get("title", "")).replace("\n", " ")
        lines.append(f"{i+1}. {clean_title} (Link: {news.get('link','')})")
    return lines


def _deduplicate_candidates(news_list: List[dict]) -> List[dict]:
    seen_links: set[str] = set()
    unique_candidates: List[dict] = []
    for item in news_list:
        link = str(item.get("link", ""))
        if link and link not in seen_links:
            unique_candidates.append(item)
            seen_links.add(link)
    return unique_candidates


def fetch_recent_candidates(*, feed_data: dict, logger) -> List[dict]:
    category_candidates: List[dict] = []
    rss_urls = feed_data.get("rss", [])
    for raw_url in rss_urls:
        url = str(raw_url).split("#")[0].strip()
        if not url:
            continue
        try:
            feed = _parse_feed_url(url)
            valid_count = 0
            for entry in feed.entries:
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                    if datetime.now() - dt > timedelta(hours=24):
                        continue

                category_candidates.append({"title": f"[RSS] {entry.title}", "link": entry.link})
                valid_count += 1
                logger.info(f"  📥 抓取命中 -> {entry.title} ({entry.link})")

            logger.info(f"✅ RSS源 [{url}] 抓取完成，共获得 {valid_count} 条有效资讯")
        except Exception as e:
            logger.error(f"⚠️ RSS抓取失败 [{url}]: {e}")

    return _deduplicate_candidates(category_candidates)


def _validate_and_repair(raw: str) -> List[dict]:
    """
    尝试解析 AI 返回的 JSON。
    解析成功：返回 items 列表（可能为空）
    解析失败：返回空列表（该批次内容丢弃，不发出去）
    """
    try:
        # 尝试提取 JSON 代码块
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            # 尝试直接解析整个响应
            text = raw.strip()

        data = json.loads(text)
        items = data.get("items", [])
        if not isinstance(items, list):
            return []

        repaired = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            summary = str(item.get("summary", "")).strip()
            # 防御：url 必须有效，否则跳过
            if url and url.startswith(("http://", "https://")):
                repaired.append({"title": title, "url": url, "summary": summary})

        return repaired
    except Exception:
        return []


def run_prompt_debug(*, config: dict, category_name: str, news_list: List[dict], category_prompt: str, logger) -> dict:
    if not news_list:
        return {
            "status": "empty_candidates",
            "category": category_name,
            "candidate_count": 0,
            "selected_items": [],
            "preview_markdown": "",
            "batches": [],
            "system_prompt": _build_system_prompt(config.get("ai", {}).get("system_prompt", ""), category_prompt),
        }

    system_prompt = _build_system_prompt(config.get("ai", {}).get("system_prompt", ""), category_prompt)
    all_items_md = _build_candidate_lines(news_list)
    all_selected: List[dict] = []
    batch_results = []

    for batch_idx in range(0, len(all_items_md), MAX_ITEMS_PER_BATCH):
        batch_lines = all_items_md[batch_idx:batch_idx + MAX_ITEMS_PER_BATCH]
        input_text = "【待筛选列表】：\n" + "\n".join(batch_lines)
        batch_no = batch_idx // MAX_ITEMS_PER_BATCH + 1
        logger.info(f"🤖 AI 分析 [{category_name}] 批次 {batch_no}（{len(batch_lines)} 条）")

        batch_record = {
            "batch_no": batch_no,
            "candidate_count": len(batch_lines),
            "raw_response": "",
            "parsed_items": [],
            "status": "pending",
        }

        for attempt in range(MAX_RETRIES):
            try:
                raw = chat_completion(
                    api_url=config["ai"]["api_url"],
                    api_key=config["ai"]["api_key"],
                    model=config["ai"]["model"],
                    system_prompt=system_prompt,
                    user_text=input_text,
                    temperature=0.1,
                    timeout_s=120,
                    json_mode=True,
                )
                items = _validate_and_repair(raw)
                batch_record["raw_response"] = raw
                batch_record["parsed_items"] = items
                batch_record["status"] = "success" if items else "empty"
                all_selected.extend(items)
                break
            except Exception as e:
                batch_record["status"] = "error"
                batch_record["error"] = str(e)
                logger.warning(f"⚠️ AI 分析第 {attempt + 1} 次尝试失败 [{category_name}]: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_S)
                else:
                    logger.error(f"❌ AI 分析彻底失败 [{category_name}]")
                    batch_results.append(batch_record)
                    return {
                        "status": "error",
                        "category": category_name,
                        "candidate_count": len(news_list),
                        "selected_items": [],
                        "preview_markdown": "",
                        "batches": batch_results,
                        "system_prompt": system_prompt,
                        "error": str(e),
                    }

        batch_results.append(batch_record)
        time.sleep(3)

    seen_urls: set[str] = set()
    unique: List[dict] = []
    for item in all_selected:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique.append(item)

    if not unique:
        logger.info(f"🈳 AI 判定 [{category_name}] 无合格内容，已拦截。")
        return {
            "status": "empty",
            "category": category_name,
            "candidate_count": len(news_list),
            "selected_items": [],
            "preview_markdown": "",
            "batches": batch_results,
            "system_prompt": system_prompt,
        }

    logger.info(f"✅ [{category_name}] 共筛选出 {len(unique)} 条有效内容")
    return {
        "status": "success",
        "category": category_name,
        "candidate_count": len(news_list),
        "selected_items": unique,
        "preview_markdown": _render_markdown(category_name, unique),
        "batches": batch_results,
        "system_prompt": system_prompt,
    }


def _ai_process_category(*, config: dict, category_name: str, news_list: List[dict], category_prompt: str, logger) -> Optional[str]:
    debug_result = run_prompt_debug(
        config=config,
        category_name=category_name,
        news_list=news_list,
        category_prompt=category_prompt,
        logger=logger,
    )
    if debug_result["status"] != "success":
        return None
    return debug_result["preview_markdown"]


def run_task(*, config: dict, logger) -> None:
    logger.info("=" * 40)
    logger.info("🚀 === 营销情报抓取任务开始 ===")
    logger.info("=" * 40)

    settings = config.get("settings", {})

    today_str = datetime.now().strftime("%m-%d")
    title_template = settings.get("report_title", "📅 营销情报早报 | {date}")
    header_msg = f"# {title_template.replace('{date}', today_str)}\n> 正在为您通过 AI 融合检索定向信源与全网热词..."
    send_markdown_to_app(
        cid=config["wecom"]["cid"],
        secret=config["wecom"]["secret"],
        agent_id=str(config["wecom"]["aid"]),
        content=header_msg,
    )

    has_any_update = False

    for category, feed_data in config.get("feeds", {}).items():
        logger.info(f"\n📁 正在处理板块: 【{category}】")
        category_candidates = fetch_recent_candidates(feed_data=feed_data, logger=logger)

        # 关键词接口预留（当前休眠）
        keywords = feed_data.get("keywords", [])
        if keywords:
            pass

        if category_candidates:
            logger.info(f"⏳ 板块 【{category}】 排重后剩余 {len(category_candidates)} 条数据交由 AI 筛选...")
            ai_summary = _ai_process_category(
                config=config,
                category_name=category,
                news_list=category_candidates,
                category_prompt=feed_data.get("prompt", ""),
                logger=logger,
            )

            if ai_summary:
                msg_body = ai_summary
                logger.info(f"📤 推送板块 【{category}】 成功")
                send_markdown_to_app(
                    cid=config["wecom"]["cid"],
                    secret=config["wecom"]["secret"],
                    agent_id=str(config["wecom"]["aid"]),
                    content=msg_body,
                )
                has_any_update = True
                time.sleep(2)
        else:
            logger.info(f"📭 板块 【{category}】 今日无更新数据")

    if has_any_update:
        if settings.get("show_footer", True):
            send_markdown_to_app(
                cid=config["wecom"]["cid"],
                secret=config["wecom"]["secret"],
                agent_id=str(config["wecom"]["aid"]),
                content=f"\n{settings.get('footer_text', '')}",
            )
        logger.info("✅ 任务圆满完成")
    else:
        empty_msg = settings.get("empty_message", "📭 今日全网无重要更新。")
        send_markdown_to_app(
            cid=config["wecom"]["cid"],
            secret=config["wecom"]["secret"],
            agent_id=str(config["wecom"]["aid"]),
            content=empty_msg,
        )
        logger.info("📭 今日全网无更新内容被推送")
