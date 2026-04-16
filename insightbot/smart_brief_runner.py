import json
import re
import time
from datetime import datetime, timedelta
from html import unescape
from typing import Any, List, Optional

import feedparser
import requests

from .ai import chat_completion

# ---------- constants ----------
MAX_RETRIES = 3
RETRY_DELAY_S = 5
FEED_FETCH_TIMEOUT_S = 15
DEFAULT_SELECTION_SETTINGS = {
    "max_selected_items": 5,
    "title_max_len": 50,
    "summary_max_len": 30,
    "full_context_threshold_chars": 18000,
    "batch_size": 15,
}
DEBUG_SAMPLE_NEWS = [
    {
        "title": "[RSS] 微信视频号广告 ROI 提升 30%，品牌主加速布局",
        "link": "https://example.com/001",
        "summary": "平台广告投放效率提升，品牌预算正在向视频号倾斜，适合观察内容投放与转化闭环的新玩法。",
    },
    {
        "title": "[RSS] 小红书推出品牌号新功能：支持直链跳转电商平台",
        "link": "https://example.com/002",
        "summary": "品牌号链路更接近效果广告与种草转化一体化，适合评估小红书站内外闭环经营机会。",
    },
    {
        "title": "[RSS] AI 文案工具月活突破 500 万，营销效率提升显著",
        "link": "https://example.com/003",
        "summary": "AI 工具继续向营销执行层渗透，值得关注内容生产与团队分工方式的变化。",
    },
    {
        "title": "[RSS] 某明星离婚八卦新闻（无关内容，测试拦截）",
        "link": "https://example.com/004",
        "summary": "娱乐八卦，无品牌传播方法论，也没有营销行业参考价值。",
    },
    {
        "title": "[RSS] 抖音电商 GMV 同比增长 45%，直播带货进入精细化运营阶段",
        "link": "https://example.com/005",
        "summary": "平台增速和运营方式变化对品牌直播策略、投放节奏和内容组织都有参考意义。",
    },
]

DEFAULT_SYSTEM_PROMPT = """你是一个拥有 10 年经验的资深营销情报官。
你的任务：从新闻列表中，挑选出与中国市场营销、公关传播最具参考价值的资讯，每条输出一句话影响点评。

【行业聚焦】
优先关注：生活方式、运动、时尚、地产、酒店、消费品牌等行业动态。
剔除：低价值通稿、自媒体八卦、人事变动、娱乐新闻、算法学术论文、与营销无关的纯技术内容。"""


def _render_markdown(category: str, items: List[dict]) -> str:
    blocks = [f"## {category}\n"]
    for item in items:
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        summary = item.get("summary", "").strip()
        if not url:
            continue
        blocks.append(f"### [{title}]({url})\n")
        blocks.append(f"> 💡 *{summary}*\n\n")
    return "".join(blocks).strip()


def get_selection_settings(config: dict[str, Any]) -> dict[str, int]:
    raw = (config.get("ai", {}) or {}).get("selection", {})
    settings = dict(DEFAULT_SELECTION_SETTINGS)
    if isinstance(raw, dict):
        for key, default in DEFAULT_SELECTION_SETTINGS.items():
            value = raw.get(key)
            if isinstance(value, int) and value > 0:
                settings[key] = value
    return settings


def _build_system_prompt(
    base_system_prompt: str,
    category_prompt: str = "",
    *,
    selection_settings: dict[str, int],
) -> str:
    max_selected_items = selection_settings["max_selected_items"]
    title_max_len = selection_settings["title_max_len"]
    summary_max_len = selection_settings["summary_max_len"]

    system_prompt = (base_system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    system_prompt += f"""

【输出格式】
你必须返回 JSON 对象，不要返回任何其他内容，且 items 最多 {max_selected_items} 条：
{{
  "items": [
    {{
      "title": "重写后的简体中文标题（必须去除'震惊''重磅''突发'等虚假修饰词；结构：[主体] + [核心动作]；不超过{title_max_len}字）",
      "url": "原文链接（必须保留，不可省略）",
      "summary": "一句话摘要（{summary_max_len}字以内，简体中文，平实老练，指出对营销人的具体启示）"
    }}
  ]
}}

【关键规则】
- 宁缺毋滥：若列表中没有任何符合标准的新闻，返回 {{"items": []}}
- 最多只保留 {max_selected_items} 条最有价值的内容
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
        clean_title = str(news.get("title", "")).replace("\n", " ").strip()
        clean_summary = str(news.get("summary", "")).replace("\n", " ").strip()
        summary_part = f" | Summary: {clean_summary}" if clean_summary else ""
        lines.append(f"{i+1}. {clean_title}{summary_part} (Link: {news.get('link','')})")
    return lines


def _make_input_text(news_list: List[dict]) -> str:
    return "【待筛选列表】：\n" + "\n".join(_build_candidate_lines(news_list))


def _clean_text(value: str, *, limit: int = 240) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _extract_entry_summary(entry) -> str:
    candidates = []
    if hasattr(entry, "summary"):
        candidates.append(getattr(entry, "summary"))
    if hasattr(entry, "description"):
        candidates.append(getattr(entry, "description"))

    content_items = getattr(entry, "content", None)
    if isinstance(content_items, list):
        for item in content_items:
            if isinstance(item, dict):
                candidates.append(item.get("value", ""))
            else:
                candidates.append(getattr(item, "value", ""))

    for candidate in candidates:
        cleaned = _clean_text(candidate)
        if cleaned:
            return cleaned
    return ""


def _truncate_text(value: str, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" ，,.;；。") + "..."


def _normalize_ai_items(items: List[dict], *, selection_settings: dict[str, int]) -> List[dict]:
    normalized: List[dict] = []
    seen_urls: set[str] = set()
    title_max_len = selection_settings["title_max_len"]
    summary_max_len = selection_settings["summary_max_len"]
    max_selected_items = selection_settings["max_selected_items"]

    for item in items:
        if not isinstance(item, dict):
            continue

        url = str(item.get("url", "")).strip()
        if not url or not url.startswith(("http://", "https://")) or url in seen_urls:
            continue

        title = _truncate_text(item.get("title", ""), limit=title_max_len)
        summary = _truncate_text(item.get("summary", ""), limit=summary_max_len)
        if not title:
            continue

        normalized.append({"title": title, "url": url, "summary": summary})
        seen_urls.add(url)
        if len(normalized) >= max_selected_items:
            break

    return normalized


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

                summary = _extract_entry_summary(entry)
                category_candidates.append(
                    {
                        "title": f"[RSS] {entry.title}",
                        "link": entry.link,
                        "summary": summary,
                    }
                )
                valid_count += 1
                logger.info(f"  📥 抓取命中 -> {entry.title} ({entry.link})")

            logger.info(f"✅ RSS源 [{url}] 抓取完成，共获得 {valid_count} 条有效资讯")
        except Exception as e:
            logger.error(f"⚠️ RSS抓取失败 [{url}]: {e}")

    return _deduplicate_candidates(category_candidates)


def _validate_and_repair(raw: str, *, selection_settings: dict[str, int] | None = None) -> List[dict]:
    selection_settings = selection_settings or DEFAULT_SELECTION_SETTINGS
    try:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        text = match.group(1) if match else raw.strip()
        data = json.loads(text)
        items = data.get("items", [])
        if not isinstance(items, list):
            return []
        return _normalize_ai_items(items, selection_settings=selection_settings)
    except Exception:
        return []


def _call_selection_once(
    *,
    config: dict,
    category_name: str,
    news_list: List[dict],
    category_prompt: str,
    logger,
    selection_settings: dict[str, int],
    stage_label: str,
    batch_no: int,
) -> dict[str, Any]:
    system_prompt = _build_system_prompt(
        config.get("ai", {}).get("system_prompt", ""),
        category_prompt,
        selection_settings=selection_settings,
    )
    input_text = _make_input_text(news_list)
    batch_record = {
        "stage": stage_label,
        "batch_no": batch_no,
        "candidate_count": len(news_list),
        "input_chars": len(input_text),
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
            items = _validate_and_repair(raw, selection_settings=selection_settings)
            batch_record["raw_response"] = raw
            batch_record["parsed_items"] = items
            batch_record["status"] = "success" if items else "empty"
            return {
                "ok": True,
                "record": batch_record,
                "items": items,
                "system_prompt": system_prompt,
                "error": None,
            }
        except Exception as e:
            batch_record["status"] = "error"
            batch_record["error"] = str(e)
            logger.warning(f"⚠️ AI 分析第 {attempt + 1} 次尝试失败 [{category_name} / {stage_label} #{batch_no}]: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_S)
            else:
                logger.error(f"❌ AI 分析彻底失败 [{category_name} / {stage_label} #{batch_no}]")
                return {
                    "ok": False,
                    "record": batch_record,
                    "items": [],
                    "system_prompt": system_prompt,
                    "error": str(e),
                }
    return {
        "ok": False,
        "record": batch_record,
        "items": [],
        "system_prompt": system_prompt,
        "error": "unknown",
    }


def run_prompt_debug(*, config: dict, category_name: str, news_list: List[dict], category_prompt: str, logger) -> dict:
    selection_settings = get_selection_settings(config)
    system_prompt = _build_system_prompt(
        config.get("ai", {}).get("system_prompt", ""),
        category_prompt,
        selection_settings=selection_settings,
    )

    if not news_list:
        return {
            "status": "empty_candidates",
            "category": category_name,
            "candidate_count": 0,
            "selected_items": [],
            "preview_markdown": "",
            "batches": [],
            "system_prompt": system_prompt,
            "selection_mode": "empty",
        }

    batch_results: List[dict[str, Any]] = []
    total_input_text = _make_input_text(news_list)
    threshold = selection_settings["full_context_threshold_chars"]
    batch_size = selection_settings["batch_size"]

    if len(total_input_text) <= threshold:
        logger.info(f"🤖 AI 全量分析 [{category_name}]（{len(news_list)} 条）")
        result = _call_selection_once(
            config=config,
            category_name=category_name,
            news_list=news_list,
            category_prompt=category_prompt,
            logger=logger,
            selection_settings=selection_settings,
            stage_label="full",
            batch_no=1,
        )
        batch_results.append(result["record"])
        if not result["ok"]:
            return {
                "status": "error",
                "category": category_name,
                "candidate_count": len(news_list),
                "selected_items": [],
                "preview_markdown": "",
                "batches": batch_results,
                "system_prompt": system_prompt,
                "selection_mode": "full",
                "error": result["error"],
            }
        unique = result["items"]
        selection_mode = "full"
    else:
        logger.info(
            f"🤖 AI 分片分析 [{category_name}]（{len(news_list)} 条，输入 {len(total_input_text)} chars，阈值 {threshold}）"
        )
        stage_one_selected: List[dict] = []
        for start in range(0, len(news_list), batch_size):
            batch_news = news_list[start:start + batch_size]
            batch_no = start // batch_size + 1
            logger.info(f"🤖 AI 分析 [{category_name}] 分片 {batch_no}（{len(batch_news)} 条）")
            result = _call_selection_once(
                config=config,
                category_name=category_name,
                news_list=batch_news,
                category_prompt=category_prompt,
                logger=logger,
                selection_settings=selection_settings,
                stage_label="chunk",
                batch_no=batch_no,
            )
            batch_results.append(result["record"])
            if not result["ok"]:
                return {
                    "status": "error",
                    "category": category_name,
                    "candidate_count": len(news_list),
                    "selected_items": [],
                    "preview_markdown": "",
                    "batches": batch_results,
                    "system_prompt": system_prompt,
                    "selection_mode": "chunked",
                    "error": result["error"],
                }
            stage_one_selected.extend(result["items"])
            time.sleep(3)

        deduped_stage_one = _normalize_ai_items(stage_one_selected, selection_settings=selection_settings)
        if not deduped_stage_one:
            unique = []
        else:
            logger.info(f"🤖 AI 总选 [{category_name}]（{len(deduped_stage_one)} 条入围候选）")
            final_result = _call_selection_once(
                config=config,
                category_name=category_name,
                news_list=deduped_stage_one,
                category_prompt=category_prompt,
                logger=logger,
                selection_settings=selection_settings,
                stage_label="final",
                batch_no=1,
            )
            batch_results.append(final_result["record"])
            if not final_result["ok"]:
                return {
                    "status": "error",
                    "category": category_name,
                    "candidate_count": len(news_list),
                    "selected_items": [],
                    "preview_markdown": "",
                    "batches": batch_results,
                    "system_prompt": system_prompt,
                    "selection_mode": "chunked",
                    "error": final_result["error"],
                }
            unique = final_result["items"]
        selection_mode = "chunked"

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
            "selection_mode": selection_mode,
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
        "selection_mode": selection_mode,
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


def run_task(*, config: dict, logger) -> dict:
    """
    Classic pipeline (per-category fetch → AI filter → return markdown).
    Does NOT send to any channel. Channel dispatch is owned by task_runner.
    Returns {"ok": bool, "final_markdown": str, "error": str|None}.
    """
    logger.info("=" * 40)
    logger.info("🚀 === 营销情报抓取任务开始 ===")
    logger.info("=" * 40)

    final_blocks = []
    has_any_update = False

    for category, feed_data in config.get("feeds", {}).items():
        logger.info(f"\n📁 正在处理板块: 【{category}】")
        category_candidates = fetch_recent_candidates(feed_data=feed_data, logger=logger)

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
                logger.info(f"📤 板块 【{category}】 精选完成")
                final_blocks.append(ai_summary)
                has_any_update = True
        else:
            logger.info(f"📭 板块 【{category}】 今日无更新数据")

    final_markdown = "\n\n".join(final_blocks)

    if not has_any_update:
        logger.info("📭 今日全网无更新内容")
    else:
        logger.info("✅ 任务完成")

    return {
        "ok": True,
        "final_markdown": final_markdown,
        "error": None,
    }
