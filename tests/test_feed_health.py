import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from insightbot.feed_health import (
    CACHE_TTL_SECONDS,
    get_feed_health_snapshot,
    inspect_feed,
    inspect_feeds,
    load_health_cache,
    save_health_cache,
)


def _make_entry(title: str, link: str, hours_ago: float = 1.0):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    pub_time = datetime.now() - timedelta(hours=hours_ago)
    entry.published_parsed = pub_time.timetuple()
    return entry


def _make_feed(entries: list, *, bozo: bool = False, bozo_exception: Exception | None = None):
    feed = MagicMock()
    feed.entries = entries
    feed.bozo = bozo
    feed.bozo_exception = bozo_exception
    feed.feed = {"title": "Example Feed"} if entries or not bozo else {}
    return feed


def _make_http_response(content: bytes = b"<rss></rss>"):
    response = MagicMock()
    response.content = content
    response.raise_for_status.return_value = None
    return response


class TestInspectFeed:

    def test_recent_feed_is_ok(self):
        feed = _make_feed([_make_entry("近期文章", "https://example.com/recent", hours_ago=2)])

        with patch("insightbot.feed_health.requests.get", return_value=_make_http_response()):
            with patch("insightbot.feed_health.feedparser.parse", return_value=feed):
                result = inspect_feed("https://example.com/feed.xml")

        assert result["status"] == "ok"
        assert result["recent_entries"] == 1
        assert result["error_type"] is None

    def test_stale_feed_is_marked_stale(self):
        feed = _make_feed([_make_entry("过期文章", "https://example.com/stale", hours_ago=48)])

        with patch("insightbot.feed_health.requests.get", return_value=_make_http_response()):
            with patch("insightbot.feed_health.feedparser.parse", return_value=feed):
                result = inspect_feed("https://example.com/feed.xml")

        assert result["status"] == "stale"
        assert result["recent_entries"] == 0
        assert result["total_entries"] == 1

    def test_bozo_without_entries_is_parse_error(self):
        feed = _make_feed([], bozo=True, bozo_exception=ValueError("bad xml"))

        with patch("insightbot.feed_health.requests.get", return_value=_make_http_response()):
            with patch("insightbot.feed_health.feedparser.parse", return_value=feed):
                result = inspect_feed("https://example.com/feed.xml")

        assert result["status"] == "error"
        assert result["error_type"] == "parse_error"

    def test_network_timeout_is_classified(self):
        with patch("insightbot.feed_health.requests.get", side_effect=TimeoutError("timed out")):
            result = inspect_feed("https://example.com/feed.xml")

        assert result["status"] == "error"
        assert result["error_type"] == "timeout"


class TestInspectFeeds:

    def test_aggregates_category_counts(self):
        first_feed = _make_feed([_make_entry("近期文章", "https://example.com/recent", hours_ago=1)])
        second_feed = _make_feed([_make_entry("过期文章", "https://example.com/stale", hours_ago=36)])

        with patch("insightbot.feed_health.requests.get", side_effect=[_make_http_response(), _make_http_response()]):
            with patch("insightbot.feed_health.feedparser.parse", side_effect=[first_feed, second_feed]):
                snapshot = inspect_feeds(
                    {
                        "营销": {"rss": ["https://example.com/1.xml"], "prompt": ""},
                        "政策": {"rss": ["https://example.com/2.xml"], "prompt": ""},
                    }
                )

        assert snapshot["counts"] == {"ok": 1, "stale": 1, "error": 0}
        assert len(snapshot["categories"]) == 2


class TestHealthCache:

    def test_save_and_load_cache(self, tmp_path):
        payload = {"checked_at": datetime.now().isoformat(timespec="seconds"), "counts": {"ok": 1, "stale": 0, "error": 0}}
        with patch.dict("os.environ", {"FEED_HEALTH_CACHE_FILE": str(tmp_path / "feed_health_cache.json")}, clear=False):
            save_health_cache(str(tmp_path), payload)
            loaded = load_health_cache(str(tmp_path))

        assert loaded is not None
        assert loaded["counts"]["ok"] == 1
        assert loaded["is_stale"] is False

    def test_get_snapshot_uses_cache_when_fresh(self, tmp_path):
        payload = {"checked_at": datetime.now().isoformat(timespec="seconds"), "counts": {"ok": 2, "stale": 0, "error": 0}, "categories": []}
        cache_path = tmp_path / "feed_health_cache.json"
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with patch.dict("os.environ", {"FEED_HEALTH_CACHE_FILE": str(cache_path)}, clear=False):
            snapshot = get_feed_health_snapshot({}, bot_dir=str(tmp_path), use_cache=True, force_refresh=False)

        assert snapshot["source"] == "cache"
        assert snapshot["counts"]["ok"] == 2

    def test_get_snapshot_refreshes_when_cache_missing(self, tmp_path):
        payload = {
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "counts": {"ok": 0, "stale": 0, "error": 0},
            "categories": [],
            "error_types": {},
        }
        with patch.dict("os.environ", {"FEED_HEALTH_CACHE_FILE": str(tmp_path / "feed_health_cache.json")}, clear=False):
            with patch("insightbot.feed_health.inspect_feeds", return_value=payload):
                snapshot = get_feed_health_snapshot({}, bot_dir=str(tmp_path), use_cache=True, force_refresh=False)

        assert snapshot["source"] == "fresh"
        assert snapshot["cache_age_seconds"] == 0

    def test_stale_cache_flag_when_expired(self, tmp_path):
        old_dt = datetime.now() - timedelta(seconds=CACHE_TTL_SECONDS + 10)
        payload = {"checked_at": old_dt.isoformat(timespec="seconds"), "counts": {"ok": 1, "stale": 0, "error": 0}, "categories": []}
        cache_path = tmp_path / "feed_health_cache.json"
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with patch.dict("os.environ", {"FEED_HEALTH_CACHE_FILE": str(cache_path)}, clear=False):
            loaded = load_health_cache(str(tmp_path))

        assert loaded is not None
        assert loaded["is_stale"] is True
