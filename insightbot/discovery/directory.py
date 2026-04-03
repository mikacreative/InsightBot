"""
目录策略：通过扫描 RSS 目录站点发现 RSS 源
抓取 RSSHub、热榜等页面，解析 <link rel="alternate" type="application/rss+xml">
"""

import re
import logging
from typing import List, Optional

from insightbot.discovery.base import DiscoveryStrategy

logger = logging.getLogger(__name__)

DIRECTORY_SOURCES = [
    {
        "name": "rsshub",
        "url": "https://rsshub.app",
    },
    {
        "name": "feed43",
        "url": "https://feed43.com",
    },
]


class DirectoryStrategy(DiscoveryStrategy):
    """
    目录扫描策略
    通过抓取 RSS 目录站点，解析页面中的 RSS link 标签来发现订阅源。
    """

    def __init__(
        self,
        timeout: int = 10,
        user_agent: Optional[str] = None,
    ):
        self.timeout = timeout
        self.user_agent = user_agent or (
            "InsightBot/1.0 (RSS Discovery; +https://github.com/mikacreative/InsightBot)"
        )

    @property
    def strategy_name(self) -> str:
        return "directory"

    def _fetch_page(self, url: str) -> Optional[str]:
        """抓取单个页面"""
        try:
            import httpx
        except ImportError:
            logger.warning("[DirectoryStrategy] httpx not installed: pip install httpx")
            return None

        try:
            resp = httpx.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning(f"[DirectoryStrategy] Failed to fetch {url}: {e}")
            return None

    def _extract_feeds_from_html(self, html: str, source_name: str) -> List[dict]:
        """从 HTML 页面中提取 RSS link 标签"""
        feeds = []

        # 模式: <link rel="alternate" type="application/rss+xml" href="...">
        link_pattern = re.compile(
            r'<link[^>]+type=["\']application/rss\+xml["\'][^>]+href=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        for match in link_pattern.finditer(html):
            feed_url = match.group(1).strip()
            if feed_url and feed_url.startswith("http"):
                feeds.append({
                    "feed_url": feed_url,
                    "discovery_query": source_name,
                    "source_strategy": self.strategy_name,
                    "reason": f"从目录站点 {source_name} 发现",
                })

        # 模式2: <link href="..." type="application/rss+xml" ...>
        link_pattern2 = re.compile(
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\']application/rss\+xml["\']',
            re.IGNORECASE,
        )
        for match in link_pattern2.finditer(html):
            feed_url = match.group(1).strip()
            if feed_url and feed_url.startswith("http"):
                feeds.append({
                    "feed_url": feed_url,
                    "discovery_query": source_name,
                    "source_strategy": self.strategy_name,
                    "reason": f"从目录站点 {source_name} 发现",
                })

        return feeds

    def discover(
        self, keywords: List[str], existing_urls: List[str]
    ) -> List[dict]:
        """扫描目录站点发现 RSS 源"""
        all_feeds = []

        for source in DIRECTORY_SOURCES:
            source_name = source["name"]
            source_url = source["url"]

            logger.info(f"[DirectoryStrategy] Scanning {source_name}: {source_url}")
            html = self._fetch_page(source_url)
            if not html:
                continue

            feeds = self._extract_feeds_from_html(html, source_name)
            logger.info(f"[DirectoryStrategy] Found {len(feeds)} feeds from {source_name}")
            all_feeds.extend(feeds)

        # URL 精确去重
        seen = set()
        unique_feeds = []
        for feed in all_feeds:
            url = feed["feed_url"]
            if url not in seen:
                seen.add(url)
                unique_feeds.append(feed)

        return unique_feeds
