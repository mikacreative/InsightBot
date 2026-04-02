import json
import re
import time
from datetime import datetime, timedelta

import feedparser

from .ai import chat_completion
from .wecom import send_markdown_to_app

# ---------- constants ----------
MAX_ITEMS_PER_BATCH = 15   # 每批交给 AI 的新闻条数
MAX_RETRIES = 3
RETRY_DELAY_S = 5

# 简化的 system prompt（格式规则全部由代码处理，AI 只负责判断和提炼）
SYSTEM_PROMPT_TEMPLATE = """你是一个拥有 10 年经验的资深营销情报官。
你的任务：从新闻列表中，挑选出与中国市场营销、公关传播最具参考价值的资讯，每条输出一句话影响点评。

【行业聚焦】
优先关注：生活方式、运动、时尚、地产、酒店、消费品牌等行业动态。
剔除：低价值通稿、自媒体八卦、人事变动、娱乐新闻、算法学术论文、与营销无关的纯技术内容。

【输出格式】
你必须返回 JSON 对象，不要返回任何其他内容：
{{
  "items": [
    {{
      "title": "重写后的简体中文标题（必须去除'震惊''重磅''突发'等虚假修饰词；结构：[主体] + [核心动作]；不超过50字）",
      "url": "原文链接（必须保留，不可省略）",
      "summary": "一句话摘要（30字以内，简体中文，平实老练，指出对营销人的具体启示）"
    }}
  ]
}}

【关键规则】
- 宁缺毋滥：若列表中没有任何符合标准的新闻，返回 {{"items": []}}
- url 必须为有效链接，不可为空，不可省略
- 摘要必须使用简体中文
- 不要输出任何解释、说明或开场白，只输出 JSON"""
# --------------------------------


def _render_markdown(category: str, items: list[dict]) -> str:
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


def _validate_and_repair(raw: str) -> list[dict]:
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


def _ai_process_category(*, config: dict, category_name: str, news_list: list[dict], category_prompt: str, logger) -> str | None:
    if not news_list:
        return None

    # 构建 user_text（分批，每批最多 MAX_ITEMS_PER_BATCH 条）
    all_items_md = []
    for i, news in enumerate(news_list):
        clean_title = str(news.get("title", "")).replace("\n", " ")
        all_items_md.append(f"{i+1}. {clean_title} (Link: {news.get('link','')})")

    system_prompt = SYSTEM_PROMPT_TEMPLATE
    if category_prompt:
        system_prompt += f"\n\n【本板块额外筛选标准】：\n{category_prompt}"

    # 分批处理
    batch_size = MAX_ITEMS_PER_BATCH
    all_selected: list[dict] = []

    for batch_idx in range(0, len(all_items_md), batch_size):
        batch_lines = all_items_md[batch_idx:batch_idx + batch_size]
        input_text = "【待筛选列表】：\n" + "\n".join(batch_lines)

        logger.info(f"🤖 AI 分析 [{category_name}] 批次 {batch_idx // batch_size + 1}（{len(batch_lines)} 条）")

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
                all_selected.extend(items)
                break
            except Exception as e:
                logger.warning(f"⚠️ AI 分析第 {attempt + 1} 次尝试失败 [{category_name}]: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_S)
                else:
                    logger.error(f"❌ AI 分析彻底失败 [{category_name}]")
                    return None

        time.sleep(3)  # 批次间稍作喘息

    if not all_selected:
        logger.info(f"🈳 AI 判定 [{category_name}] 无合格内容，已拦截。")
        return None

    # 去重（按 url）
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for item in all_selected:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique.append(item)

    logger.info(f"✅ [{category_name}] 共筛选出 {len(unique)} 条有效内容")
    return _render_markdown(category_name, unique)


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
        category_candidates: list[dict] = []

        rss_urls = feed_data.get("rss", [])
        for raw_url in rss_urls:
            url = str(raw_url).split("#")[0].strip()
            if not url:
                continue
            try:
                feed = feedparser.parse(url)
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

        # 关键词接口预留（当前休眠）
        keywords = feed_data.get("keywords", [])
        if keywords:
            pass

        if category_candidates:
            seen_links: set[str] = set()
            unique_candidates: list[dict] = []
            for item in category_candidates:
                link = str(item.get("link", ""))
                if link and link not in seen_links:
                    unique_candidates.append(item)
                    seen_links.add(link)

            logger.info(f"⏳ 板块 【{category}】 排重后剩余 {len(unique_candidates)} 条数据交由 AI 筛选...")
            ai_summary = _ai_process_category(
                config=config,
                category_name=category,
                news_list=unique_candidates,
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
