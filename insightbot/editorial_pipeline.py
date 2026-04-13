"""
Editorial Pipeline — 双阶段编辑流水线

Stage 1: build_global_candidates   — 聚合所有 RSS 候选，形成统一候选池
Stage 2: screen_global_candidates   — 全局初筛，站在"总编辑"视角做一轮精选
Stage 3: assign_candidates_to_categories — 单归属板块分配
Stage 4: select_for_category       — 板块最终精选与改写（复用现有逻辑）
"""

import json
import logging
from datetime import datetime

import feedparser
import re
import time
import uuid
from datetime import timedelta
from html import unescape
from typing import Any

import feedparser
import requests

from .ai import chat_completion
from .wecom import send_markdown_to_app
from .smart_brief_runner import (
    _build_system_prompt,
    _call_selection_once,
    _clean_text,
    _deduplicate_candidates,
    _extract_entry_summary,
    _make_input_text,
    _normalize_ai_items,
    _parse_feed_url,
    _truncate_text,
    get_selection_settings,
)

# ---------- constants ----------
FEED_FETCH_TIMEOUT_S = 15
MAX_RETRIES = 3
RETRY_DELAY_S = 5

DEFAULT_GLOBAL_SELECTION_SETTINGS = {
    "max_selected_items": 10,
    "title_max_len": 50,
    "summary_max_len": 60,
    "full_context_threshold_chars": 20000,
    "batch_size": 20,
}

DEFAULT_GLOBAL_SYSTEM_PROMPT = """你是一个资深营销情报官，站在"总编辑"视角对全局候选做初筛。

【你的职责】
从候选列表中筛选出两类内容：
1. 今天最值得进入简报的内容（高价值、时效性强）
2. 暂时不确定但板块层可以继续判断的内容（有一定价值但需板块进一步确认）

【排除标准】
- 低价值通稿、自媒体八卦、人事变动、娱乐新闻
- 与营销/品牌传播完全无关的纯技术论文
- 标题含有"震惊""重磅""突发"等虚假修饰词的内容

【输出要求】
返回 JSON 对象，最多 {max_selected_items} 条：
{{
  "items": [
    {{
      "title": "原始标题",
      "link": "原文链接",
      "summary": "原始摘要",
      "priority_score": 0.0-1.0,
      "editorial_note": "简短的全局初筛理由"
    }}
  ]
}}

【关键规则】
- 宁缺毋滥，没有符合标准的内容返回 {{"items": []}}
- 不要输出任何解释，只输出 JSON
"""


# ---------- Stage 1: Build Global Candidates ----------


def build_global_candidates(*, config: dict, logger) -> list[dict]:
    """
    聚合所有板块 RSS 源，形成统一候选池（GlobalCandidate 列表）。
    只做工程清洗，不做板块判断。
    """
    all_candidates: list[dict] = []
    feeds_config = config.get("feeds", {})

    for category, feed_data in feeds_config.items():
        rss_urls = feed_data.get("rss", [])
        for raw_url in rss_urls:
            url = str(raw_url).split("#")[0].strip()
            if not url:
                continue
            try:
                feed = _parse_feed_url(url)
                for entry in feed.entries:
                    # 时间窗过滤：24h 以内
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        if datetime.now() - dt > timedelta(hours=24):
                            continue

                    summary = _extract_entry_summary(entry)
                    candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, entry.link or entry.title))

                    all_candidates.append({
                        "id": candidate_id,
                        "title": f"[RSS] {entry.title}",
                        "link": entry.link,
                        "summary": summary,
                        "published_at": getattr(entry, "published", ""),
                        "source_url": entry.link,
                        "source_name": getattr(entry, "author_detail", {}).get("name", url),
                        "source_category_hint": category,
                    })
                logger.info(f"✅ 全局抓取 [{category}] [{url}] — {len(feed.entries)} 条")
            except Exception as e:
                logger.warning(f"⚠️ 全局抓取失败 [{url}]: {e}")

    # 去重（按 link）
    unique_candidates = _deduplicate_candidates(all_candidates)
    logger.info(f"📦 全局候选池：{len(all_candidates)} 条 → 去重后 {len(unique_candidates)} 条")

    return unique_candidates


# ---------- Stage 2: Screen Global Candidates ----------


def _build_global_system_prompt(
    base_system_prompt: str = "",
    *,
    selection_settings: dict[str, int],
    publication_scope: str = "",
) -> str:
    max_selected_items = selection_settings["max_selected_items"]
    title_max_len = selection_settings["title_max_len"]
    summary_max_len = selection_settings["summary_max_len"]

    prompt = (base_system_prompt or DEFAULT_GLOBAL_SYSTEM_PROMPT).strip()
    prompt = prompt.format(
        max_selected_items=max_selected_items,
        title_max_len=title_max_len,
        summary_max_len=summary_max_len,
    )

    if publication_scope:
        prompt += f"\n\n【刊物整体栏目定位】：\n{publication_scope}"

    prompt += f"""
【输出格式】
返回 JSON，最多 {max_selected_items} 条：
{{
  "items": [
    {{
      "title": "标题",
      "link": "链接",
      "summary": "摘要",
      "priority_score": 0.0-1.0,
      "editorial_note": "理由"
    }}
  ]
}}

- 没有符合内容时返回 {{"items": []}}
- 只输出 JSON，不输出任何解释"""
    return prompt


def _validate_global_screen(raw: str, *, selection_settings: dict[str, int]) -> list[dict]:
    """解析全局初筛的 AI 返回，提取 priority_score + editorial_note。"""
    try:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        text = match.group(1) if match else raw.strip()
        data = json.loads(text)
        items = data.get("items", [])
        if not isinstance(items, list):
            return []
        # 标准化：补全字段，去重
        normalized = []
        seen_urls = set()
        max_items = selection_settings["max_selected_items"]
        title_max_len = selection_settings["title_max_len"]
        summary_max_len = selection_settings["summary_max_len"]

        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link", "")).strip()
            if not url or url in seen_urls:
                continue
            title = _truncate_text(item.get("title", ""), limit=title_max_len)
            summary = _truncate_text(item.get("summary", ""), limit=summary_max_len)
            if not title:
                continue
            normalized.append({
                "title": title,
                "link": url,
                "summary": summary,
                "priority_score": float(item.get("priority_score", 0.5)),
                "editorial_note": str(item.get("editorial_note", "")),
            })
            seen_urls.add(url)
            if len(normalized) >= max_items:
                break
        return normalized
    except Exception:
        return []


def screen_global_candidates(
    *,
    config: dict,
    candidates: list[dict],
    logger,
) -> dict:
    """
    全局初筛：站在"总编辑"视角对候选池做一轮精选。
    返回 {
        "ok": bool,
        "screened": list[dict],   # 通过初筛的候选
        "global_shortlist_size": int,
        "selection_mode": "full" | "chunked",
        "batches": list[dict],
        "system_prompt": str,
        "error": str | None,
    }
    """
    editorial_config = (config.get("ai", {}) or {}).get("editorial_pipeline", {})
    selection_settings = dict(DEFAULT_GLOBAL_SELECTION_SETTINGS)
    raw_settings = editorial_config.get("selection", {})
    if isinstance(raw_settings, dict):
        for key, default in DEFAULT_GLOBAL_SELECTION_SETTINGS.items():
            value = raw_settings.get(key)
            if isinstance(value, int) and value > 0:
                selection_settings[key] = value

    # 计算 shortlist 目标数量：3x 全局倍率
    multiplier = editorial_config.get("global_shortlist_multiplier", 3)
    target_shortlist = selection_settings["max_selected_items"] * multiplier

    logger.info(
        f"🔍 全局初筛开始：{len(candidates)} 条候选，"
        f"目标 shortlist ~{target_shortlist} 条（{multiplier}x倍率）"
    )

    if not candidates:
        return {
            "ok": True,
            "screened": [],
            "global_shortlist_size": 0,
            "selection_mode": "empty",
            "batches": [],
            "system_prompt": "",
            "error": None,
        }

    # 构建 system prompt
    publication_scope = ""
    if editorial_config.get("inject_publication_scope_into_global", True):
        publication_scope = _build_publication_scope_summary(config)

    system_prompt = _build_global_system_prompt(
        config.get("ai", {}).get("system_prompt", ""),
        selection_settings=selection_settings,
        publication_scope=publication_scope,
    )
    input_text = _make_input_text(candidates)

    threshold = selection_settings["full_context_threshold_chars"]
    batch_size = selection_settings["batch_size"]

    batch_results: list[dict] = []

    if len(input_text) <= threshold:
        # 全量模式
        logger.info(f"🤖 全局初筛 — 全量模式（{len(candidates)} 条）")
        result = _call_global_screen_once(
            config=config,
            news_list=candidates,
            system_prompt=system_prompt,
            selection_settings=selection_settings,
            stage_label="global_full",
            batch_no=1,
        )
        batch_results.append(result["record"])
        if not result["ok"]:
            return {
                "ok": False,
                "screened": [],
                "global_shortlist_size": 0,
                "selection_mode": "full",
                "batches": batch_results,
                "system_prompt": system_prompt,
                "error": result["error"],
            }
        screened = result["items"]
        selection_mode = "full"
    else:
        # 分片模式
        logger.info(f"🤖 全局初筛 — 分片模式（{len(candidates)} 条，{len(input_text)} chars）")
        stage_one_selected: list[dict] = []
        for start in range(0, len(candidates), batch_size):
            batch_news = candidates[start:start + batch_size]
            batch_no = start // batch_size + 1
            result = _call_global_screen_once(
                config=config,
                news_list=batch_news,
                system_prompt=system_prompt,
                selection_settings=selection_settings,
                stage_label="global_chunk",
                batch_no=batch_no,
            )
            batch_results.append(result["record"])
            if not result["ok"]:
                return {
                    "ok": False,
                    "screened": [],
                    "global_shortlist_size": 0,
                    "selection_mode": "chunked",
                    "batches": batch_results,
                    "system_prompt": system_prompt,
                    "error": result["error"],
                }
            stage_one_selected.extend(result["items"])
            time.sleep(3)

        # 去重 + 截断到目标数量
        deduped = _normalize_global_items(stage_one_selected, selection_settings=selection_settings)
        # 取 top target_shortlist
        deduped.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        screened = deduped[:target_shortlist]
        selection_mode = "chunked"

    logger.info(f"✅ 全局初筛完成：通过 {len(screened)} 条（模式: {selection_mode}）")
    return {
        "ok": True,
        "screened": screened,
        "global_shortlist_size": len(screened),
        "selection_mode": selection_mode,
        "batches": batch_results,
        "system_prompt": system_prompt,
        "error": None,
    }


def _call_global_screen_once(
    *,
    config: dict,
    news_list: list[dict],
    system_prompt: str,
    selection_settings: dict[str, int],
    stage_label: str,
    batch_no: int,
) -> dict:
    """对一批候选做全局初筛单次调用。"""
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
            items = _validate_global_screen(raw, selection_settings=selection_settings)
            batch_record["raw_response"] = raw
            batch_record["parsed_items"] = items
            batch_record["status"] = "success" if items else "empty"
            return {
                "ok": True,
                "record": batch_record,
                "items": items,
                "error": None,
            }
        except Exception as e:
            batch_record["status"] = "error"
            batch_record["error"] = str(e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_S)
            else:
                return {
                    "ok": False,
                    "record": batch_record,
                    "items": [],
                    "error": str(e),
                }
    return {
        "ok": False,
        "record": batch_record,
        "items": [],
        "error": "unknown",
    }


def _normalize_global_items(items: list[dict], *, selection_settings: dict[str, int]) -> list[dict]:
    """对全局初筛结果去重 + 字段补全。"""
    normalized = []
    seen_urls = set()
    title_max_len = selection_settings["title_max_len"]
    summary_max_len = selection_settings["summary_max_len"]

    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link", "")).strip()
        if not url or url in seen_urls:
            continue
        title = _truncate_text(item.get("title", ""), limit=title_max_len)
        summary = _truncate_text(item.get("summary", ""), limit=summary_max_len)
        if not title:
            continue
        normalized.append({
            "title": title,
            "link": url,
            "summary": summary,
            "priority_score": float(item.get("priority_score", 0.5)),
            "editorial_note": str(item.get("editorial_note", "")),
        })
        seen_urls.add(url)
    return normalized


def _build_publication_scope_summary(config: dict) -> str:
    """从 config 构建刊物整体栏目定位摘要，注入全局初筛。"""
    feeds = config.get("feeds", {})
    lines = []
    for category, feed_data in feeds.items():
        prompt = feed_data.get("prompt", "")
        lines.append(f"【{category}】{prompt}")
    return "\n".join(lines)


# ---------- Stage 3: Assign Candidates to Categories ----------


def assign_candidates_to_categories(
    *,
    config: dict,
    screened_candidates: list[dict],
    logger,
) -> dict:
    """
    单归属板块分配：每条候选只分配给一个最合适的板块。
    返回 {
        "ok": bool,
        "category_candidate_map": dict[str, list[dict]],
        "unassigned": list[dict],
        "error": str | None,
    }
    """
    editorial_config = (config.get("ai", {}) or {}).get("editorial_pipeline", {})
    allow_multi = editorial_config.get("allow_multi_assign", False)
    feeds = config.get("feeds", {})

    if not screened_candidates:
        return {
            "ok": True,
            "category_candidate_map": {cat: [] for cat in feeds},
            "unassigned": [],
            "error": None,
        }

    # 按 batch_size 分批分配
    batch_size = editorial_config.get("assignment_batch_size", 20)
    category_map: dict[str, list[dict]] = {cat: [] for cat in feeds}
    unassigned: list[dict] = []

    for start in range(0, len(screened_candidates), batch_size):
        batch = screened_candidates[start:start + batch_size]
        batch_no = start // batch_size + 1
        logger.info(f"🔀 板块分配批次 {batch_no}（{len(batch)} 条）")

        result = _assign_batch_once(
            config=config,
            candidates=batch,
            feeds=feeds,
            allow_multi=allow_multi,
            batch_no=batch_no,
        )

        for cat, assigned in result["assignments"].items():
            category_map[cat].extend(assigned)

        unassigned.extend(result["unassigned"])
        time.sleep(2)

    # 统计日志
    for cat, items in category_map.items():
        logger.info(f"  📬 【{cat}】分配了 {len(items)} 条")

    return {
        "ok": True,
        "category_candidate_map": category_map,
        "unassigned": unassigned,
        "error": None,
    }


def _assign_batch_once(
    *,
    config: dict,
    candidates: list[dict],
    feeds: dict,
    allow_multi: bool,
    batch_no: int,
) -> dict:
    """单批次板块分配。"""
    category_list = list(feeds.keys())
    if not category_list:
        return {"assignments": {}, "unassigned": candidates}

    input_lines = []
    for i, c in enumerate(candidates):
        clean_title = c.get("title", "").replace("\n", " ").strip()
        clean_summary = c.get("summary", "").replace("\n", " ").strip()
        input_lines.append(
            f"{i+1}. [{clean_title}]({c.get('link', '')}) | {clean_summary} | "
            f"source_hint: {c.get('source_category_hint', '未知')}"
        )
    input_text = "【待分配候选】：\n" + "\n".join(input_lines)

    category_lines = []
    for cat in category_list:
        prompt = feeds[cat].get("prompt", "")
        category_lines.append(f"- **{cat}**：{prompt}")
    category_text = "\n".join(category_lines)

    system_prompt = f"""你是一个板块分配助手。请将以下候选内容分配到最合适的板块。

【可用板块】：
{category_text}

【分配规则】
- 一条内容只分配给一个板块（单归属）
- 根据板块的筛选标准，选择最匹配的板块
- 如果内容与所有板块都不匹配，返回空分配

【输出格式】返回 JSON：
{{
  "assignments": [
    {{
      "candidate_index": 1,
      "assigned_category": "板块名称",
      "reason": "分配理由"
    }}
  ]
}}

只输出 JSON，不要解释。"""

    batch_record = {
        "stage": "assignment",
        "batch_no": batch_no,
        "candidate_count": len(candidates),
        "input_chars": len(input_text),
        "raw_response": "",
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
            batch_record["raw_response"] = raw
            batch_record["status"] = "success"
            assignments_raw = _parse_assignment_response(raw)
            break
        except Exception as e:
            batch_record["status"] = "error"
            batch_record["error"] = str(e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_S)
            else:
                assignments_raw = []
    else:
        assignments_raw = []

    # 构建分配映射
    result_map: dict[str, list[dict]] = {cat: [] for cat in category_list}
    assigned_indices = set()

    for assignment in assignments_raw:
        idx = assignment.get("candidate_index", 0) - 1
        cat = assignment.get("assigned_category", "")
        if 0 <= idx < len(candidates) and cat in result_map:
            candidate = dict(candidates[idx])
            candidate["assignment_reason"] = assignment.get("reason", "")
            result_map[cat].append(candidate)
            assigned_indices.add(idx)

    unassigned = [c for i, c in enumerate(candidates) if i not in assigned_indices]

    return {
        "assignments": result_map,
        "unassigned": unassigned,
        "record": batch_record,
    }


def _parse_assignment_response(raw: str) -> list[dict]:
    """解析板块分配 AI 返回。"""
    try:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        text = match.group(1) if match else raw.strip()
        data = json.loads(text)
        items = data.get("assignments", [])
        if isinstance(items, list):
            return items
        return []
    except Exception:
        return []


# ---------- Stage 4: Per-Category Final Selection ----------
# 复用 smart_brief_runner.run_prompt_debug


def select_for_category(
    *,
    config: dict,
    category_name: str,
    candidates: list[dict],
    logger,
):
    """板块最终精选（复用 run_prompt_debug）。"""
    from .smart_brief_runner import run_prompt_debug

    feed_data = config.get("feeds", {}).get(category_name, {})
    category_prompt = feed_data.get("prompt", "")

    # 转换为 run_prompt_debug 期望的格式
    news_list = [
        {"title": c.get("title", ""), "link": c.get("link", ""), "summary": c.get("summary", "")}
        for c in candidates
    ]

    return run_prompt_debug(
        config=config,
        category_name=category_name,
        news_list=news_list,
        category_prompt=category_prompt,
        logger=logger,
    )


# ---------- Orchestration ----------


def run_editorial_pipeline(*, config: dict, logger) -> dict:
    """
    主编流水线完整编排。
    返回完整中间结果，便于调试：
    {
        "ok": bool,
        "global_candidates": [...],
        "screened_result": {...},
        "assignment_result": {...},
        "category_results": dict[str, {...}],
        "final_markdown": str,
        "error": str | None,
    }
    """
    editorial_config = (config.get("ai", {}) or {}).get("editorial_pipeline", {})
    enabled = editorial_config.get("enabled", False)

    logger.info("=" * 40)
    logger.info("📡 Editorial Pipeline 开始")
    logger.info(f"   enabled={enabled}")
    logger.info("=" * 40)

    # Stage 1: 全局候选池
    logger.info("📦 Stage 1: 构建全局候选池")
    global_candidates = build_global_candidates(config=config, logger=logger)

    # Stage 2: 全局初筛
    logger.info("🔍 Stage 2: 全局初筛")
    screened_result = screen_global_candidates(
        config=config,
        candidates=global_candidates,
        logger=logger,
    )

    if not screened_result["ok"]:
        return {
            "ok": False,
            "global_candidates": global_candidates,
            "screened_result": screened_result,
            "assignment_result": {},
            "category_results": {},
            "final_markdown": "",
            "error": screened_result.get("error"),
        }

    # Stage 3: 板块分配
    logger.info("🔀 Stage 3: 板块分配")
    assignment_result = assign_candidates_to_categories(
        config=config,
        screened_candidates=screened_result["screened"],
        logger=logger,
    )

    # Stage 4: 板块最终精选
    logger.info("✂️  Stage 4: 板块最终精选")
    category_results = {}
    final_blocks = []

    for category in config.get("feeds", {}).keys():
        cat_candidates = assignment_result["category_candidate_map"].get(category, [])
        if not cat_candidates:
            logger.info(f"  🈳 【{category}】无候选，跳过")
            continue

        logger.info(f"  ✂️  【{category}】{len(cat_candidates)} 条候选进行最终精选")
        result = select_for_category(
            config=config,
            category_name=category,
            candidates=cat_candidates,
            logger=logger,
        )
        category_results[category] = result

        if result.get("status") == "success" and result.get("preview_markdown"):
            final_blocks.append(result["preview_markdown"])
            logger.info(f"  ✅ 【{category}】最终输出 {len(result.get('selected_items', []))} 条")
        else:
            logger.info(f"  🚫 【{category}】无合格内容被拦截")

    final_markdown = "\n\n".join(final_blocks)

    # --- WeChat 推送 ---
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
    for block in final_blocks:
        send_markdown_to_app(
            cid=config["wecom"]["cid"],
            secret=config["wecom"]["secret"],
            agent_id=str(config["wecom"]["aid"]),
            content=block,
        )
        has_any_update = True
        time.sleep(2)

    if has_any_update:
        if settings.get("show_footer", True):
            send_markdown_to_app(
                cid=config["wecom"]["cid"],
                secret=config["wecom"]["secret"],
                agent_id=str(config["wecom"]["aid"]),
                content=f"\n{settings.get('footer_text', '')}",
            )
        logger.info("✅ Editorial Pipeline 推送完成")
    else:
        empty_msg = settings.get("empty_message", "📭 今日全网无重要更新。")
        send_markdown_to_app(
            cid=config["wecom"]["cid"],
            secret=config["wecom"]["secret"],
            agent_id=str(config["wecom"]["aid"]),
            content=empty_msg,
        )
        logger.info("📭 今日无内容推送")

    return {
        "ok": True,
        "global_candidates": global_candidates,
        "screened_result": screened_result,
        "assignment_result": assignment_result,
        "category_results": category_results,
        "final_markdown": final_markdown,
        "error": None,
    }
