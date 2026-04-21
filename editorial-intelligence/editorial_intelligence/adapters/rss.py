"""
RSS/Atom adapter for official direct feeds.

Collects from direct RSS/Atom URLs without any intermediate proxy.
These sources carry the highest trust weight (SourceWeightConfig.official = 1.0).
"""

import logging
from datetime import datetime
from typing import Any

import feedparser

from .base import NormalizedSignal, SourceAdapter

logger = logging.getLogger(__name__)


class RSSAdapter(SourceAdapter):
    """
    Collects items from RSS/Atom feeds.

    Accepts a list of feed URLs or a dict mapping feed_id -> url.
    """

    def __init__(self, rsshub_base_url: str = ""):
        """
        Args:
            rsshub_base_url: Optional RSSHub base URL for feeds that require it.
                             If empty, only direct RSS/Atom URLs are collected.
        """
        self.rsshub_base_url = rsshub_base_url.rstrip("/")

    def collect(
        self,
        feeds: list[str] | dict[str, str] | None = None,
        feed_urls: list[str] | None = None,
        **kwargs: Any,
    ) -> list[NormalizedSignal]:
        """
        Collect from one or more RSS/Atom feeds.

        Args:
            feeds: Either a list of RSS URLs, or a dict of {feed_id: url}.
            feed_urls: Alias for feeds (list form).
        """
        if feeds is None and feed_urls is None:
            return []
        if feed_urls is not None:
            feeds = feed_urls

        signals: list[NormalizedSignal] = []
        feed_map: dict[str, str]

        if isinstance(feeds, list):
            feed_map = {url.split("#")[0].strip(): url for url in feeds if url.split("#")[0].strip()}
        else:
            feed_map = feeds  # type: ignore[assignment]

        for feed_id, url in feed_map.items():
            # Strip inline comments (e.g. "https://example.com/rss # My Feed")
            clean_url = url.split("#")[0].strip()
            if not clean_url:
                continue
            try:
                signals.extend(self._fetch_feed(feed_id, clean_url))
            except Exception as e:
                logger.warning(f"Failed to fetch feed {feed_id} ({clean_url}): {e}")

        return signals

    def _fetch_feed(self, feed_id: str, url: str) -> list[NormalizedSignal]:
        parsed = feedparser.parse(url)
        signals: list[NormalizedSignal] = []

        for entry in parsed.entries:
            # RSS 2.0: entry.get('published_parsed'), Atom: entry.get('updated_parsed')
            published = self._parse_date(entry)
            summary = self._extract_summary(entry)

            signals.append(
                NormalizedSignal(
                    source_type="official",
                    source_id=feed_id,
                    title=entry.get("title", "").strip(),
                    summary=summary,
                    url=self._best_link(entry),
                    published_at=published,
                    signals={},
                    raw=entry,
                )
            )

        logger.info(f"Collected {len(signals)} signals from {feed_id}")
        return signals

    def _best_link(self, entry: Any) -> str:
        """Prefer href on Atom link elements, fall back to href attr."""
        if hasattr(entry, "href"):
            return entry.href
        if hasattr(entry, "link"):
            return entry.link
        for link in getattr(entry, "links", []):
            if link.get("rel") == "alternate" or not link.get("rel"):
                return link.get("href", "")
        return ""

    def _extract_summary(self, entry: Any) -> str:
        if hasattr(entry, "summary"):
            return self._strip_html(entry.summary)
        if hasattr(entry, "description"):
            return self._strip_html(entry.description)
        if hasattr(entry, "content"):
            for c in entry.content:
                if c.get("type", "").startswith("text"):
                    return self._strip_html(c.value)
        return ""

    def _strip_html(self, html: str) -> str:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()

    def _parse_date(self, entry: Any) -> str:
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            parsed = getattr(entry, attr, None)
            if parsed:
                try:
                    return datetime(*parsed[:6]).isoformat()
                except Exception:
                    pass
        return ""
