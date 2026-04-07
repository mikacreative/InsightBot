import json
import socket
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError

import feedparser

from .paths import feed_health_cache_file_path

CACHE_TTL_SECONDS = 300


def _now() -> datetime:
    return datetime.now()


def _normalize_feed_url(raw_url: str) -> str:
    return str(raw_url).split("#")[0].strip()


def _classify_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", str(exc) or "请求超时"
    if isinstance(exc, URLError):
        return "unreachable", str(exc.reason) if getattr(exc, "reason", None) else str(exc)

    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout", str(exc)
    if any(token in text for token in ("connection refused", "name or service not known", "nodename nor servname")):
        return "unreachable", str(exc)
    return "unknown_error", str(exc) or "未知错误"


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
        feed = feedparser.parse(normalized_url)
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
