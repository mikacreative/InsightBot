"""
Editorial Pipeline — 双阶段编辑流水线

Stage 1: build_global_candidates   — 聚合所有 RSS 候选，形成统一候选池
Stage 2: screen_global_candidates   — 全局初筛，站在"总编辑"视角做一轮精选
Stage 3: assign_candidates_to_categories — 单归属板块分配
Stage 4: select_for_category       — AI 板块终筛与最终标题/摘要
"""

from datetime import datetime

import re
import time
import uuid
from datetime import timedelta
from html import unescape
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

from .ai import chat_completion
from .ai_json import extract_json_object
from .smart_brief_runner import (
    _clean_text,
    _deduplicate_candidates,
    _extract_entry_summary,
    _normalize_result_url,
    _parse_feed_url,
    _render_markdown,
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
    "min_priority_score": 0.5,
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
"""


def _normalize_category_token(value: str) -> str:
    """Normalize category labels so AI responses can omit emoji/punctuation."""
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or ""))
    return text.lower()


def _resolve_category_name(raw_category: str, category_list: list[str]) -> str:
    """Map AI-returned category names to the configured category key."""
    normalized_raw = _normalize_category_token(raw_category)
    if not normalized_raw:
        return ""

    normalized_map = {
        category: _normalize_category_token(category)
        for category in category_list
    }

    for category, normalized_category in normalized_map.items():
        if normalized_raw == normalized_category:
            return category

    for category, normalized_category in normalized_map.items():
        if normalized_raw in normalized_category or normalized_category in normalized_raw:
            return category

    return ""


def _candidate_ref(index: int) -> str:
    return f"C{index + 1:03d}"


def _candidate_ref_map(candidates: list[dict]) -> dict[str, dict]:
    return {_candidate_ref(i): item for i, item in enumerate(candidates)}


def _make_candidate_ref_input(candidates: list[dict]) -> str:
    lines = []
    for i, news in enumerate(candidates):
        ref = _candidate_ref(i)
        clean_title = _clean_output_title(news.get("title", "")).replace("\n", " ").strip()
        clean_summary = str(news.get("summary", "")).replace("\n", " ").strip()
        source_hint = news.get("source_category_hint") or ",".join(news.get("source_section_hints", []) or [])
        source_name = str(news.get("source_name", "")).replace("\n", " ").strip()
        lines.append(
            f"{ref} | title: {clean_title} | summary: {clean_summary} | "
            f"source: {source_name} | source_hint: {source_hint}"
        )
    return "【候选列表】\n" + "\n".join(lines)


def _clean_output_title(value: str) -> str:
    """Remove transport/source prefixes from titles before final rendering."""
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = re.sub(r"^\[(RSS|搜索)\]\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^(文章频道|项目频道|招聘频道|案例频道)\s*[-－]\s*", "", title)
    return title.strip()


def _clean_summary_text(value: str, *, limit: int) -> str:
    """Normalize AI summary lines and reject explicit non-answers."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^[>\-\s]*", "", text).strip()
    text = re.sub(r"^💡\s*", "", text).strip()
    text = text.strip("*_` \t")
    if _is_explicit_empty_ai_response(text):
        return ""
    if not text:
        return ""
    return _truncate_text(text, limit=limit).strip("*_` \t")


def _clean_final_text(value: str) -> str:
    """Normalize AI final fields without truncating editorial content."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^[>\-\s]*", "", text).strip()
    return text.strip("*_` \t")


def _looks_truncated(value: str) -> bool:
    text = str(value or "").strip()
    return text.endswith(("...", "…")) or "..." in text


def _looks_like_code_fallback_summary(summary: str) -> bool:
    text = str(summary or "")
    fallback_markers = (
        "需关注其对品牌传播与消费沟通的影响",
        "需关注其对AI营销与平台运营的影响",
        "需关注其对企业合规与品牌声誉管理的影响",
        "需关注其对",
    )
    return any(marker in text for marker in fallback_markers)


def _validate_final_title(value: str, *, title_max_len: int) -> str:
    title = _clean_final_text(value)
    title = _clean_output_title(title)
    if _is_explicit_empty_ai_response(title):
        return ""
    if not title or len(title) > title_max_len or _looks_truncated(title):
        return ""
    return title


def _validate_final_summary(value: str, *, summary_max_len: int) -> str:
    summary = _clean_final_text(value)
    summary = re.sub(r"^💡\s*", "", summary).strip("*_` \t")
    if _is_explicit_empty_ai_response(summary):
        return ""
    if not summary or len(summary) > summary_max_len:
        return ""
    if _looks_truncated(summary) or _looks_like_code_fallback_summary(summary):
        return ""
    return summary


def _title_similarity_key(value: str) -> set[str]:
    """Small, dependency-free near-duplicate key for Chinese/English titles."""
    text = _normalize_category_token(_clean_output_title(value))
    if len(text) <= 1:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _shared_topic_markers(left: str, right: str) -> bool:
    marker_groups = (
        ("小红书", "世界杯"),
        ("claude",),
        ("openai",),
        ("豆包",),
        ("六神",),
    )
    left_lower = str(left or "").lower()
    right_lower = str(right or "").lower()
    return any(
        all(marker in left_lower and marker in right_lower for marker in group)
        for group in marker_groups
    )


def _is_similar_title(left: str, right: str, *, threshold: float = 0.7) -> bool:
    if _shared_topic_markers(left, right):
        return True
    left_key = _title_similarity_key(left)
    right_key = _title_similarity_key(right)
    if not left_key or not right_key:
        return False
    overlap = len(left_key & right_key)
    return overlap / max(1, min(len(left_key), len(right_key))) >= threshold


def _parse_score_lines(raw: str, valid_refs: set[str]) -> list[dict]:
    """Parse line output: C001 | 0.90 | reason."""
    parsed: list[dict] = []
    seen: set[str] = set()
    for line in str(raw or "").splitlines():
        match = re.search(
            r"\b(?P<ref>C\d{3})\b\s*(?:[|,，:：\-]\s*)?"
            r"(?P<score>0(?:\.\d+)?|1(?:\.0+)?|\.\d+)\s*(?:[|,，:：\-]\s*)?(?P<reason>.*)",
            line.strip(),
        )
        if not match:
            continue
        ref = match.group("ref")
        if ref not in valid_refs or ref in seen:
            continue
        try:
            score = float(match.group("score"))
        except ValueError:
            continue
        if not 0 <= score <= 1:
            continue
        parsed.append({
            "ref": ref,
            "score": score,
            "reason": match.group("reason").strip(),
        })
        seen.add(ref)
    return parsed


def _parse_assignment_lines(raw: str, valid_refs: set[str], category_list: list[str]) -> list[dict]:
    """Parse line output: C001 | category | reason."""
    parsed: list[dict] = []
    seen: set[str] = set()
    for line in str(raw or "").splitlines():
        parts = [part.strip() for part in re.split(r"\s*[|]\s*", line.strip(), maxsplit=2)]
        if len(parts) < 2:
            continue
        ref = parts[0].lstrip("-* ").strip()
        if ref not in valid_refs or ref in seen:
            continue
        category = _resolve_category_name(parts[1], category_list)
        if not category:
            continue
        parsed.append({
            "ref": ref,
            "assigned_category": category,
            "reason": parts[2] if len(parts) > 2 else "",
        })
        seen.add(ref)
    return parsed


def _parse_summary_lines(raw: str, valid_refs: set[str], *, summary_max_len: int) -> dict[str, str]:
    """Parse line output: C001 | rewritten summary."""
    summaries: dict[str, str] = {}
    for line in str(raw or "").splitlines():
        parts = [part.strip() for part in re.split(r"\s*[|]\s*", line.strip(), maxsplit=1)]
        if len(parts) != 2:
            continue
        ref = parts[0].lstrip("-* ").strip()
        if ref in valid_refs and ref not in summaries:
            summary = _clean_summary_text(parts[1], limit=summary_max_len)
            if summary:
                summaries[ref] = summary
    return summaries


def _parse_final_edit_lines(
    raw: str,
    valid_refs: set[str],
    *,
    title_max_len: int,
    summary_max_len: int,
) -> dict[str, dict]:
    """Parse Stage 4 output: C001 | KEEP/DROP | final title | final summary | reason."""
    parsed: dict[str, dict] = {}
    for line in str(raw or "").splitlines():
        parts = [part.strip() for part in re.split(r"\s*[|]\s*", line.strip(), maxsplit=4)]
        if len(parts) < 2:
            continue
        ref = parts[0].lstrip("-* ").strip()
        if ref not in valid_refs or ref in parsed:
            continue
        status = parts[1].upper()
        if status not in {"KEEP", "DROP"}:
            continue
        reason = parts[4] if len(parts) > 4 else ""
        if status == "DROP":
            parsed[ref] = {
                "status": "DROP",
                "title": "",
                "summary": "",
                "reason": reason,
            }
            continue
        if len(parts) < 4:
            continue
        title = _validate_final_title(parts[2], title_max_len=title_max_len)
        summary = _validate_final_summary(parts[3], summary_max_len=summary_max_len)
        if not title or not summary:
            continue
        parsed[ref] = {
            "status": "KEEP",
            "title": title,
            "summary": summary,
            "reason": reason,
        }
    return parsed


def _is_explicit_empty_ai_response(raw: str) -> bool:
    text = str(raw or "").strip().lower()
    return text in {"none", "no", "empty", "无", "无合格内容", "没有符合内容"}


def _parse_global_screen_response(
    raw: str,
    news_list: list[dict],
    *,
    selection_settings: dict[str, int],
) -> list[dict]:
    """Map minimal AI score lines back to code-owned candidates."""
    ref_map = _candidate_ref_map(news_list)
    parsed = _parse_score_lines(raw, set(ref_map))
    items: list[dict] = []
    max_items = selection_settings["max_selected_items"]
    min_score = float(selection_settings.get("min_priority_score", 0.5))

    for entry in parsed:
        if entry["score"] < min_score:
            continue
        candidate = dict(ref_map[entry["ref"]])
        candidate["priority_score"] = entry["score"]
        candidate["editorial_note"] = entry["reason"]
        items.append(candidate)
        if len(items) >= max_items:
            break

    return _normalize_global_items(items, selection_settings=selection_settings)


def _resolve_source_hint_category(candidate: dict, category_list: list[str]) -> str:
    """Resolve a fallback category using source_section_hints/source_category_hint."""
    raw_hints: list[str] = []
    if candidate.get("source_category_hint"):
        raw_hints.append(str(candidate.get("source_category_hint", "")))
    hints = candidate.get("source_section_hints", []) or []
    if isinstance(hints, str):
        raw_hints.append(hints)
    elif isinstance(hints, list):
        raw_hints.extend(str(hint) for hint in hints)

    for hint in raw_hints:
        category = _resolve_category_name(hint, category_list)
        if category and _source_hint_auto_assign_allowed(candidate, category):
            return category
    return ""


def _source_hint_auto_assign_allowed(candidate: dict, category: str) -> bool:
    """Use source hints as defaults, but require semantic evidence for broad policy feeds."""
    normalized_category = _normalize_category_token(category)
    text = _candidate_search_text(candidate)
    if "政策" not in normalized_category:
        return True

    policy_markers = (
        "政策", "监管", "法规", "规定", "条例", "合规", "标准", "意见",
        "办法", "规划", "通知", "通报", "国务院", "发改委", "工信部",
        "市场监管", "网信", "生态环境部", "央行", "证监会", "商务部", "教育部",
        "消费者权益", "高考", "涉考", "限时上锁", "限制", "两部门", "计量",
        "gov", "miit",
    )
    return any(marker.lower() in text for marker in policy_markers)


def _candidate_search_text(candidate: dict) -> str:
    """Combine stable candidate fields for category gate checks."""
    return " ".join(
        str(candidate.get(key, ""))
        for key in (
            "title",
            "summary",
            "source_name",
            "source_url",
        )
    ).lower()


def _get_final_selection_settings(config: dict) -> dict[str, int]:
    """Use existing final-selection settings; fall back to editorial settings if needed."""
    settings = get_selection_settings(config)
    ai_config = config.get("ai", {}) or {}
    if ai_config.get("selection"):
        return settings
    editorial_settings = (
        (ai_config.get("editorial_pipeline", {}) or {}).get("selection", {})
    )
    if isinstance(editorial_settings, dict):
        for key in ("max_selected_items", "title_max_len", "summary_max_len"):
            value = editorial_settings.get(key)
            if isinstance(value, int) and value > 0:
                settings[key] = value
    return settings


def _get_sections_config(config: dict) -> dict:
    return (config.get("sections", {}) or {}) if config.get("sections") else (config.get("feeds", {}) or {})


def _get_search_config(config: dict) -> dict:
    sources = config.get("sources", {}) or {}
    if isinstance(sources.get("search"), dict):
        return sources.get("search", {}) or {}
    return config.get("search", {}) or {}


def _get_rss_sources(config: dict) -> list[dict]:
    sources = config.get("sources", {}) or {}
    rss_sources = sources.get("rss", [])
    if rss_sources:
        return [item for item in rss_sources if isinstance(item, dict)]

    sections = _get_sections_config(config)
    fallback: list[dict] = []
    for category, feed_data in sections.items():
        for raw_url in (feed_data or {}).get("rss", []) or []:
            raw_text = str(raw_url).strip()
            if not raw_text:
                continue
            fallback.append(
                {
                    "id": category,
                    "url": raw_text,
                    "enabled": True,
                    "tags": [category],
                    "section_hints": [category],
                }
            )
    return fallback


# ---------- Search: Global Candidate Supplementation ----------


def search_global_candidates(*, config: dict, logger) -> list[dict]:
    """
    读取 config["search"]，执行搜索引擎查询，归一化为 GlobalCandidate。
    搜索引擎可插拔（baidu / duckduckgo）。

    返回 list[GlobalCandidate]，格式与 RSS 候选完全一致。
    """
    search_config = _get_search_config(config)
    if not search_config.get("enabled", False):
        return []

    provider = search_config.get("provider", "baidu")
    queries = search_config.get("queries", [])
    if not queries:
        # 自动从各板块 keywords 生成 queries
        queries = _derive_queries_from_sections(config)
        logger.info(f"🔍 搜索 query 为空，已从栏目 keywords 自动派生 {len(queries)} 条")

    all_results: list[dict] = []
    for q in queries:
        keywords = q.get("keywords", "").strip()
        if not keywords:
            continue
        max_results = q.get("max_results", 10)
        section_hints = q.get("section_hints", [])
        if isinstance(section_hints, str):
            section_hints = [section_hints]
        elif not isinstance(section_hints, list):
            legacy_hint = str(q.get("category_hint", "")).strip()
            section_hints = [legacy_hint] if legacy_hint else []

        try:
            if provider == "baidu":
                raw_results = _search_baidu(keywords, max_results)
            elif provider == "duckduckgo":
                raw_results = _search_duckduckgo(keywords, max_results)
            else:
                logger.warning(f"⚠️ 未知搜索 provider: {provider}，跳过")
                continue

            for r in raw_results:
                normalized = _normalize_search_result(r, section_hints=section_hints)
                if normalized:
                    all_results.append(normalized)
            logger.info(f"🔍 [{provider}] 关键词「{keywords}」→ {len(raw_results)} 条")
        except Exception as e:
            logger.warning(f"⚠️ 搜索失败 [{keywords}]: {e}")

    # 同 link 去重
    unique = _deduplicate_candidates(all_results)
    logger.info(f"🔍 搜索补充：{len(unique)} 条（来自 {len(queries)} 个 query）")
    return unique


def _derive_queries_from_sections(config: dict) -> list[dict]:
    """从各栏目 keywords 自动派生搜索 query。"""
    queries = []
    sections = _get_sections_config(config)
    for category, section_data in sections.items():
        keywords = section_data.get("keywords", [])
        if not keywords:
            continue
        keywords_str = " ".join(keywords)
        queries.append({
            "keywords": keywords_str,
            "section_hints": [category],
            "max_results": 10,
            "_auto_generated": True,
        })
    return queries


def _normalize_search_result(raw: dict, *, section_hints: list[str] | None = None) -> dict | None:
    """将搜索引擎原始结果归一化为 GlobalCandidate 格式。"""
    link = _normalize_result_url(raw.get("link", ""))
    title = raw.get("title", "").strip()
    snippet = _clean_text(raw.get("snippet", ""))
    source_name = raw.get("source", "搜索结果")

    if not link or not title:
        return None

    candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, link)) if link else str(uuid.uuid4())

    return {
        "id": candidate_id,
        "title": f"[搜索] {title}",
        "link": link,
        "summary": snippet,
        "published_at": "",                              # 搜索结果无时间
        "source_url": link,
        "source_name": source_name,
        "source_category_hint": (section_hints or [""])[0] if section_hints else "",
        "source_section_hints": section_hints or [],
        "source_type": "search",
    }


def _search_baidu(keywords: str, max_results: int) -> list[dict]:
    """
    使用 requests + BeautifulSoup 搜索百度。
    腾讯云内地节点可正常访问，无需额外依赖。
    """
    results: list[dict] = []
    encoded_kw = requests.utils.quote(keywords)
    url = f"https://www.baidu.com/s?wd={encoded_kw}&rn={max_results}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for item in soup.select(".result, .result-op")[:max_results]:
        title_el = item.select_one("h3 a") or item.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        link = title_el.get("href", "")
        # 百度搜索结果 link 通常是重定向 URL，尝试取真实 URL
        if link.startswith("/"):
            link = "https://www.baidu.com" + link

        snippet_el = item.select_one(".c-abstract") or item.select_one(".content-right_8Zs40") or item.select_one("span")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        if not title or not link:
            continue
        results.append({
            "title": title,
            "link": link,
            "snippet": snippet,
            "source": "baidu",
        })

    return results


def _search_duckduckgo(keywords: str, max_results: int) -> list[dict]:
    """
    使用 duckduckgo-search 搜索，复用现有 discovery/search.py 逻辑。
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            for result in ddgs.text(keywords, max_results=max_results):
                title = result.get("title", "")
                link = result.get("href", "")
                snippet = result.get("body", "")
                if not title or not link:
                    continue
                results.append({
                    "title": title,
                    "link": link,
                    "snippet": snippet,
                    "source": "duckduckgo",
                })
    except Exception:
        pass
    return results


# ---------- Stage 1: Build Global Candidates ----------


def build_global_candidates(*, config: dict, logger) -> list[dict]:
    """
    聚合所有板块 RSS 源 + 搜索结果，形成统一候选池（GlobalCandidate 列表）。
    只做工程清洗，不做板块判断。
    """
    all_candidates: list[dict] = []
    rss_sources = _get_rss_sources(config)

    for source in rss_sources:
        raw_url = str(source.get("url", "")).strip()
        url = raw_url.split("#")[0].strip()
        if not url or not bool(source.get("enabled", True)):
            continue
        section_hints = [
            str(v).strip()
            for v in source.get("section_hints", []) or []
            if str(v).strip()
        ]
        if not section_hints:
            section_hints = [
                str(v).strip()
                for v in source.get("tags", []) or []
                if str(v).strip()
            ]
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
                    "source_category_hint": section_hints[0] if section_hints else "",
                    "source_section_hints": section_hints,
                })
            logger.info(f"✅ 全局抓取 [{source.get('id', url)}] [{url}] — {len(feed.entries)} 条")
        except Exception as e:
            logger.warning(f"⚠️ 全局抓取失败 [{url}]: {e}")

    # 搜索补充（并行）
    search_candidates = search_global_candidates(config=config, logger=logger)
    all_candidates.extend(search_candidates)

    # 全局去重（按 link）
    unique_candidates = _deduplicate_candidates(all_candidates)
    rss_count = sum(1 for c in all_candidates if c.get("source_type") != "search")
    search_count = len(all_candidates) - rss_count
    logger.info(
        f"📦 全局候选池：RSS {rss_count} + 搜索 {search_count} = "
        f"去重后 {len(unique_candidates)} 条"
    )

    return unique_candidates


# ---------- Stage 2: Screen Global Candidates ----------


def _build_global_system_prompt(
    base_system_prompt: str = "",
    *,
    selection_settings: dict[str, int],
    publication_scope: str = "",
) -> str:
    max_selected_items = selection_settings["max_selected_items"]
    _ = base_system_prompt

    prompt = DEFAULT_GLOBAL_SYSTEM_PROMPT.strip()

    if publication_scope:
        prompt += f"\n\n【刊物整体栏目定位】：\n{publication_scope}"

    prompt += f"""
【输出格式】
最多 {max_selected_items} 行，每行固定为：
C001 | 0.90 | 简短筛选理由

【关键限制】
- 只输出候选 ID、0-1 分数、理由
- 不要输出标题、链接、摘要、JSON、Markdown
- 只输出分数 >= 0.50 的内容；被排除内容不要输出
- 没有符合内容时只输出 NONE"""
    return prompt


def _validate_global_screen(raw: str, *, selection_settings: dict[str, int]) -> list[dict]:
    """解析全局初筛的 AI 返回，提取 priority_score + editorial_note。"""
    try:
        data = extract_json_object(raw)
        if data is None:
            return []
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
            if isinstance(default, int) and isinstance(value, int) and value > 0:
                selection_settings[key] = value
            elif isinstance(default, float) and isinstance(value, (int, float)) and value > 0:
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
    input_text = _make_candidate_ref_input(candidates)

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
        failed_batches: list[str] = []
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
                failed_batches.append(f"batch {batch_no}: {result['error']}")
                logger.warning(f"⚠️ 全局初筛批次 {batch_no} 失败，跳过该批次：{result['error']}")
                time.sleep(3)
                continue
            stage_one_selected.extend(result["items"])
            time.sleep(3)

        # 去重 + 截断到目标数量
        deduped = _normalize_global_items(stage_one_selected, selection_settings=selection_settings)
        # 取 top target_shortlist
        deduped.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        screened = deduped[:target_shortlist]
        selection_mode = "chunked"
        if not screened and failed_batches:
            return {
                "ok": False,
                "screened": [],
                "global_shortlist_size": 0,
                "selection_mode": selection_mode,
                "batches": batch_results,
                "system_prompt": system_prompt,
                "error": "; ".join(failed_batches),
            }

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
    input_text = _make_candidate_ref_input(news_list)
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
                json_mode=False,
            )
            items = _parse_global_screen_response(
                raw,
                news_list,
                selection_settings=selection_settings,
            )
            batch_record["raw_response"] = raw
            batch_record["parsed_items"] = items
            batch_record["status"] = "success" if items else "empty"
            if not items and not _is_explicit_empty_ai_response(raw):
                batch_record["status"] = "invalid_text"
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_S)
                    continue
                return {
                    "ok": False,
                    "record": batch_record,
                    "items": [],
                    "error": "AI output did not match score-line contract",
                }
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
    _ = selection_settings

    for item in items:
        if not isinstance(item, dict):
            continue
        url = _normalize_result_url(item.get("link", ""))
        if not url or url in seen_urls:
            continue
        title = _clean_output_title(item.get("title", ""))
        summary = str(item.get("summary", "")).strip()
        if not title:
            continue
        normalized_item = dict(item)
        normalized_item.update({
            "title": title,
            "link": url,
            "summary": summary,
            "priority_score": float(item.get("priority_score", 0.5)),
            "editorial_note": str(item.get("editorial_note", "")),
        })
        normalized.append(normalized_item)
        seen_urls.add(url)
    return normalized


def _build_publication_scope_summary(config: dict) -> str:
    """从 config 构建刊物整体栏目定位摘要，注入全局初筛。"""
    sections = _get_sections_config(config)
    lines = []
    for category, feed_data in sections.items():
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
    feeds = _get_sections_config(config)

    if not screened_candidates:
        return {
            "ok": True,
            "category_candidate_map": {cat: [] for cat in feeds},
            "unassigned": [],
            "error": None,
        }

    # 按 batch_size 分批分配。AI 先判断，source hint 只作 fallback。
    batch_size = editorial_config.get("assignment_batch_size", 20)
    category_map: dict[str, list[dict]] = {cat: [] for cat in feeds}
    unassigned: list[dict] = []
    category_list = list(feeds.keys())

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

        for candidate in result["unassigned"]:
            fallback_category = _resolve_source_hint_category(candidate, category_list)
            if fallback_category:
                assigned_candidate = dict(candidate)
                assigned_candidate["assignment_reason"] = "source_hint_fallback"
                category_map[fallback_category].append(assigned_candidate)
            else:
                unassigned.append(candidate)
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
    _ = allow_multi
    category_list = list(feeds.keys())
    if not category_list:
        return {"assignments": {}, "unassigned": candidates}

    input_text = _make_candidate_ref_input(candidates)

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

【输出格式】
每行固定为：
C001 | 板块名称 | 简短分配理由

【关键限制】
- 只输出候选 ID、板块名称、理由
- 不要输出标题、链接、摘要、JSON、Markdown
- 没有可分配内容时只输出 NONE"""

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
                json_mode=False,
            )
            batch_record["raw_response"] = raw
            assignments_raw = _parse_assignment_lines(
                raw,
                set(_candidate_ref_map(candidates)),
                category_list,
            )
            batch_record["status"] = "success" if assignments_raw else "empty"
            if not assignments_raw and not _is_explicit_empty_ai_response(raw):
                batch_record["status"] = "invalid_text"
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_S)
                    continue
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
    ref_to_index = {ref: idx for idx, ref in enumerate(_candidate_ref_map(candidates))}

    for assignment in assignments_raw:
        idx = ref_to_index.get(assignment.get("ref", ""), -1)
        cat = _resolve_category_name(assignment.get("assigned_category", ""), category_list)
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
        data = extract_json_object(raw)
        if data is None:
            return []
        items = data.get("assignments", [])
        if isinstance(items, list):
            return items
        return []
    except Exception:
        return []


# ---------- Stage 4: Per-Category Final Selection ----------


def select_for_category(
    *,
    config: dict,
    category_name: str,
    candidates: list[dict],
    logger,
):
    """板块最终输出：AI 终筛并生成标题/摘要，代码只校验和渲染。"""
    settings = _get_final_selection_settings(config)
    max_items = settings["max_selected_items"]
    title_max_len = settings["title_max_len"]
    summary_max_len = settings["summary_max_len"]

    if not candidates:
        return {
            "status": "empty_candidates",
            "selected_items": [],
            "preview_markdown": "",
            "candidate_count": 0,
            "batches": [],
            "selection_mode": "ai_final_edit",
        }

    ordered_candidates = sorted(
        candidates,
        key=lambda c: float(c.get("priority_score", 0.5) or 0.5),
        reverse=True,
    )

    final_items, final_record = _final_edit_category_items(
        config=config,
        category_name=category_name,
        candidates=ordered_candidates,
        max_items=max_items,
        title_max_len=title_max_len,
        summary_max_len=summary_max_len,
    )

    if not final_items:
        return {
            "status": "empty",
            "selected_items": [],
            "preview_markdown": "",
            "candidate_count": len(candidates),
            "batches": [final_record],
            "system_prompt": final_record.get("system_prompt", ""),
            "selection_mode": "ai_final_edit",
        }

    preview_markdown = _render_markdown(category_name, final_items)
    logger.info(f"  🧩 【{category_name}】AI 最终成稿 {len(final_items)} 条")

    return {
        "status": "success",
        "selected_items": final_items,
        "preview_markdown": preview_markdown,
        "candidate_count": len(candidates),
        "batches": [final_record],
        "system_prompt": final_record.get("system_prompt", ""),
        "selection_mode": "ai_final_edit",
    }


def _final_edit_category_items(
    *,
    config: dict,
    category_name: str,
    candidates: list[dict],
    max_items: int,
    title_max_len: int,
    summary_max_len: int,
) -> tuple[list[dict], dict]:
    """Ask AI to make the final keep/drop decision and final copy."""
    input_text = _make_candidate_ref_input(candidates)
    sections = _get_sections_config(config)
    category_prompt = sections.get(category_name, {}).get("prompt", "")
    system_prompt = f"""你是资深营销情报编辑。请对当前板块候选做最终终筛，并生成最终标题和摘要。

【当前板块】
{category_name}

【板块口径】
{category_prompt}

【任务】
- 从候选中保留最多 {max_items} 条。
- 可以少于 {max_items} 条，也可以全部 DROP。
- 对 KEEP 项生成最终标题和最终摘要。
- 标题必须是完整标题，{title_max_len} 字以内，禁止用省略号结尾。
- 摘要必须是简体中文，{summary_max_len} 字以内，写清“发生了什么 + 对营销人的具体启示/影响”。
- 摘要不要机械重复标题，禁止使用“需关注其对...影响”这类通用句式。

【输出格式】
每行固定为：
C001 | KEEP | final title | final summary | reason
C002 | DROP | - | - | reason

【关键限制】
- 只能使用输入候选 ID。
- 不要输出链接、Markdown、JSON、编号列表或解释。
- 不能发明事实；链接和 Markdown 将由代码生成。
- 没有可保留内容时只输出 NONE。"""

    record = {
        "stage": "final_edit",
        "batch_no": 1,
        "candidate_count": len(candidates),
        "input_chars": len(input_text),
        "raw_response": "",
        "parsed_items": {},
        "status": "pending",
        "system_prompt": system_prompt,
    }

    valid_refs = set(_candidate_ref_map(candidates))
    ref_map = _candidate_ref_map(candidates)

    for attempt in range(MAX_RETRIES):
        try:
            raw = chat_completion(
                api_url=config["ai"]["api_url"],
                api_key=config["ai"]["api_key"],
                model=config["ai"]["model"],
                system_prompt=system_prompt,
                user_text=input_text,
                temperature=0.2,
                timeout_s=120,
                json_mode=False,
            )
            parsed = _parse_final_edit_lines(
                raw,
                valid_refs,
                title_max_len=title_max_len,
                summary_max_len=summary_max_len,
            )
            record["raw_response"] = raw
            record["parsed_items"] = parsed
            if parsed or _is_explicit_empty_ai_response(raw):
                record["status"] = "success" if parsed else "empty"
                break
            record["status"] = "invalid_text"
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_S)
        except Exception as e:
            record["status"] = "error"
            record["error"] = str(e)
            parsed = {}
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_S)
    else:
        parsed = {}

    selected_items: list[dict] = []
    for ref in ref_map:
        item = parsed.get(ref)
        if not item or item.get("status") != "KEEP":
            continue
        candidate = ref_map[ref]
        url = _normalize_result_url(candidate.get("link", ""))
        if not url:
            continue
        selected_items.append({
            "title": item["title"],
            "url": url,
            "summary": item["summary"],
        })
        if len(selected_items) >= max_items:
            break

    record["selected_count"] = len(selected_items)
    return selected_items, record


def _rewrite_category_summaries(
    *,
    config: dict,
    category_name: str,
    candidates: list[dict],
    summary_max_len: int,
) -> tuple[dict[str, str], dict]:
    """Ask AI only for summary rewrites. Formatting and links stay code-owned."""
    input_text = _make_candidate_ref_input(candidates)
    system_prompt = f"""你只负责把候选摘要改写为简体中文短句。

【当前板块】
{category_name}

【输出格式】
每行固定为：
C001 | {summary_max_len}字以内摘要

【关键限制】
- 不要筛选，不要排序，不要改变候选 ID
- 不要输出标题、链接、JSON、Markdown
- 摘要只写“发生了什么 + 对营销人的启示/影响”
- 如果无法改写，输出 NONE"""

    record = {
        "stage": "summary_rewrite",
        "batch_no": 1,
        "candidate_count": len(candidates),
        "input_chars": len(input_text),
        "raw_response": "",
        "parsed_items": {},
        "status": "pending",
        "system_prompt": system_prompt,
    }

    try:
        raw = chat_completion(
            api_url=config["ai"]["api_url"],
            api_key=config["ai"]["api_key"],
            model=config["ai"]["model"],
            system_prompt=system_prompt,
            user_text=input_text,
            temperature=0.2,
            timeout_s=90,
            json_mode=False,
        )
        summaries = _parse_summary_lines(
            raw,
            set(_candidate_ref_map(candidates)),
            summary_max_len=summary_max_len,
        )
        record["raw_response"] = raw
        record["parsed_items"] = summaries
        record["status"] = "success" if summaries else "empty"
        return summaries, record
    except Exception as e:
        record["status"] = "error"
        record["error"] = str(e)
        return {}, record


def _remove_cross_category_duplicates(result: dict, seen_titles: list[str], category_name: str) -> dict:
    """Avoid repeating the same topic across sections in the final brief."""
    selected_items = []
    dropped = 0
    for item in result.get("selected_items", []) or []:
        title = item.get("title", "")
        if any(_is_similar_title(title, seen_title) for seen_title in seen_titles):
            dropped += 1
            continue
        selected_items.append(item)
        seen_titles.append(title)

    if dropped == 0:
        return result

    filtered_result = dict(result)
    filtered_result["selected_items"] = selected_items
    filtered_result["preview_markdown"] = _render_markdown(category_name, selected_items) if selected_items else ""
    filtered_result["dedupe_dropped"] = dropped
    filtered_result["status"] = "success" if selected_items else "empty"
    return filtered_result


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

    for category in _get_sections_config(config).keys():
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

    return {
        "ok": True,
        "global_candidates": global_candidates,
        "screened_result": screened_result,
        "assignment_result": assignment_result,
        "category_results": category_results,
        "final_markdown": final_markdown,
        "error": None,
    }
