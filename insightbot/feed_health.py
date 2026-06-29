import json
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import feedparser
import requests

from .paths import feed_health_cache_file_path
from .safe_http import UnsafeURL, safe_get

CACHE_TTL_SECONDS = 300
FEED_FETCH_TIMEOUT_S = 15


_ISSUE_DESCRIPTIONS = {
    "timeout": (
        "请求超时，目标站点响应太慢或暂时不可达。",
        "稍后重试；如果连续多次超时，建议降低依赖或替换为更稳定的信源。",
    ),
    "unreachable": (
        "无法连接到目标站点，可能是域名、网络或对方服务异常。",
        "先在浏览器打开源地址确认是否可访问；不可访问则替换或停用该信源。",
    ),
    "blocked_url": (
        "该地址被安全策略拦截，通常是本机地址、内网地址或不允许访问的目标。",
        "不要在生产任务中使用该地址；改成公网可访问的 RSS 或配置受控代理服务。",
    ),
    "parse_error": (
        "返回内容无法按 RSS/Atom 正常解析。",
        "检查该地址是否仍是 RSS；如果网页能打开但不是 feed，需要换成正确订阅地址。",
    ),
    "invalid_feed": (
        "返回内容不是有效 RSS/Atom，或 HTTP 状态异常。",
        "打开源地址确认格式；如果是普通网页，先用 RSS 发现工具寻找真实 feed。",
    ),
    "unknown_error": (
        "检测时出现未归类错误。",
        "查看错误原文；如果重复出现，建议先停用该源并记录为待排查。",
    ),
}


def _now() -> datetime:
    return datetime.now()


def _normalize_feed_url(raw_url: str) -> str:
    return str(raw_url).split("#")[0].strip()


def _classify_exception(exc: Exception) -> tuple[str, str]:
    timeout_exc = getattr(requests.exceptions, "Timeout", None)
    connection_exc = getattr(requests.exceptions, "ConnectionError", None)
    http_exc = getattr(requests.exceptions, "HTTPError", None)

    timeout_types = tuple(t for t in (TimeoutError, timeout_exc) if isinstance(t, type))
    if timeout_types and isinstance(exc, timeout_types):
        return "timeout", str(exc) or "请求超时"
    if isinstance(connection_exc, type) and isinstance(exc, connection_exc):
        return "unreachable", str(exc)
    if isinstance(http_exc, type) and isinstance(exc, http_exc):
        response = getattr(exc, "response", None)
        status_code = response.status_code if response is not None else "unknown"
        return "invalid_feed", f"HTTP {status_code}"
    if isinstance(exc, UnsafeURL):
        return "blocked_url", str(exc)

    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout", str(exc)
    if any(token in text for token in ("connection refused", "name or service not known", "nodename nor servname")):
        return "unreachable", str(exc)
    return "unknown_error", str(exc) or "未知错误"


def describe_feed_issue(feed: dict[str, Any]) -> dict[str, str]:
    """Return a short Chinese diagnosis and suggested action for a feed health result."""
    status = str(feed.get("status") or "unknown")
    if status == "ok":
        return {
            "severity": "ok",
            "summary": "信源正常，最近 24 小时内有新内容。",
            "action": "无需处理。",
        }
    if status == "stale":
        latest_pub = feed.get("latest_pub")
        if latest_pub:
            summary = "信源可访问，但最近 24 小时没有新内容。"
            action = "如果这是低频媒体可以保留；如果连续多天无更新，建议补充或替换信源。"
        else:
            summary = "信源可访问，但没有可识别的发布时间。"
            action = "检查该 feed 是否长期缺少时间字段；必要时换用发布时间更完整的来源。"
        return {"severity": "warning", "summary": summary, "action": action}

    error_type = str(feed.get("error_type") or "unknown_error")
    summary, action = _ISSUE_DESCRIPTIONS.get(error_type, _ISSUE_DESCRIPTIONS["unknown_error"])
    return {
        "severity": "error",
        "summary": summary,
        "action": action,
        "raw_error": str(feed.get("error_message") or "").strip(),
    }


def _parse_entry_datetime(entry: Any) -> datetime | None:
    published = getattr(entry, "published_parsed", None)
    if published:
        return datetime.fromtimestamp(time.mktime(published))

    updated = getattr(entry, "updated_parsed", None)
    if updated:
        return datetime.fromtimestamp(time.mktime(updated))

    return None


def inspect_feed(url: str) -> dict[str, Any]:
    normalized_url = _normalize_feed_url(url)
    result: dict[str, Any] = {
        "url": normalized_url,
        "status": "error",
        "error_type": None,
        "error_message": None,
        "total_entries": 0,
        "recent_entries": 0,
        "latest_pub": None,
        "elapsed_s": None,
        "checked_at": _now().isoformat(timespec="seconds"),
    }

    if not normalized_url:
        result["error_type"] = "invalid_feed"
        result["error_message"] = "空 URL"
        return result

    try:
        start = time.time()
        response = safe_get(
            normalized_url,
            timeout=FEED_FETCH_TIMEOUT_S,
            headers={"User-Agent": "InsightBot/0.3.0 (+https://github.com/mikacreative/InsightBot)"},
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        result["elapsed_s"] = round(time.time() - start, 2)

        entries = list(getattr(feed, "entries", []))
        if getattr(feed, "bozo", False) and not entries:
            exc = getattr(feed, "bozo_exception", None)
            result["error_type"] = "parse_error"
            result["error_message"] = str(exc) if exc else "解析失败"
            return result

        if not entries and not getattr(feed, "feed", None):
            result["error_type"] = "invalid_feed"
            result["error_message"] = "返回内容不是有效 RSS/Atom"
            return result

        latest_dt: datetime | None = None
        recent_entries = 0
        now = _now()

        for entry in entries:
            dt = _parse_entry_datetime(entry)
            if dt is not None:
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
                if now - dt <= timedelta(hours=24):
                    recent_entries += 1

        result["total_entries"] = len(entries)
        result["recent_entries"] = recent_entries
        result["latest_pub"] = latest_dt.isoformat(timespec="seconds") if latest_dt else None
        result["status"] = "ok" if recent_entries > 0 else "stale"
        return result
    except Exception as exc:
        error_type, message = _classify_exception(exc)
        result["error_type"] = error_type
        result["error_message"] = message
        return result


def inspect_feeds(feeds: dict[str, Any]) -> dict[str, Any]:
    categories: list[dict[str, Any]] = []
    totals = Counter()
    error_types = Counter()

    for category_name, feed_data in feeds.items():
        raw_urls = feed_data.get("rss", [])
        feed_results: list[dict[str, Any]] = []
        category_counts = Counter()

        for raw_url in raw_urls:
            result = inspect_feed(raw_url)
            feed_results.append(result)
            category_counts[result["status"]] += 1
            totals[result["status"]] += 1
            if result.get("error_type"):
                error_types[result["error_type"]] += 1

        categories.append(
            {
                "category": category_name,
                "feed_count": len(feed_results),
                "counts": {
                    "ok": category_counts["ok"],
                    "stale": category_counts["stale"],
                    "error": category_counts["error"],
                },
                "feeds": feed_results,
            }
        )

    return {
        "checked_at": _now().isoformat(timespec="seconds"),
        "counts": {
            "ok": totals["ok"],
            "stale": totals["stale"],
            "error": totals["error"],
        },
        "error_types": dict(error_types),
        "categories": categories,
    }


def load_health_cache(bot_dir: str, *, max_age_seconds: int = CACHE_TTL_SECONDS) -> dict[str, Any] | None:
    cache_path = Path(feed_health_cache_file_path(bot_dir))
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    checked_at = payload.get("checked_at")
    if not checked_at:
        return None

    try:
        checked_dt = datetime.fromisoformat(checked_at)
    except ValueError:
        return None

    payload["cache_age_seconds"] = max(0, int((_now() - checked_dt).total_seconds()))
    payload["is_stale"] = payload["cache_age_seconds"] > max_age_seconds
    payload["cache_path"] = str(cache_path)
    return payload


def save_health_cache(bot_dir: str, payload: dict[str, Any]) -> str:
    cache_path = Path(feed_health_cache_file_path(bot_dir))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(cache_path)


def get_feed_health_snapshot(
    feeds: dict[str, Any],
    *,
    bot_dir: str,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if use_cache and not force_refresh:
        cached = load_health_cache(bot_dir)
        if cached is not None:
            cached["source"] = "cache"
            return cached

    snapshot = inspect_feeds(feeds)
    save_health_cache(bot_dir, snapshot)
    snapshot["cache_age_seconds"] = 0
    snapshot["is_stale"] = False
    snapshot["cache_path"] = feed_health_cache_file_path(bot_dir)
    snapshot["source"] = "fresh"
    return snapshot
