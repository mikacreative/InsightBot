"""
搜索引擎策略：使用 DuckDuckGo 搜索发现 RSS 源
搜索模板："{keyword} RSS feed site:cn"
"""

import logging
from typing import List, Optional

from insightbot.discovery.base import DiscoveryStrategy

logger = logging.getLogger(__name__)


class SearchStrategy(DiscoveryStrategy):
    """
    搜索引擎发现策略
    使用 duckduckgo-search 库搜索 RSS 源 URL。
    """

    def __init__(
        self,
        max_results_per_keyword: int = 5,
        search_template: Optional[str] = None,
    ):
        self.max_results_per_keyword = max_results_per_keyword
        self.search_template = search_template or "{keyword} RSS feed site:cn"

    @property
    def strategy_name(self) -> str:
        return "search"

    def _search_duckduckgo(self, query: str) -> List[str]:
        """使用 duckduckgo-search 执行搜索"""
        try:
            from ddgs import DDGS
        except ImportError:
            logger.warning(
                "[SearchStrategy] duckduckgo-search not installed. "
                "Install with: pip install duckduckgo-search"
            )
            return []

        urls = []
        try:
            with DDGS() as ddgs:
                for result in ddgs.text(query, max_results=self.max_results_per_keyword):
                    url = result.get("href", "")
                    if url and url.startswith("http"):
                        urls.append(url)
        except Exception as e:
            logger.warning(f"[SearchStrategy] Search failed for '{query}': {e}")

        return urls

    def _is_likely_rss_url(self, url: str) -> bool:
        """判断 URL 是否可能是 RSS 源"""
        url_lower = url.lower()
        rss_indicators = ["/rss", "/feed", ".rss", ".xml", "/atom", "/feed.xml", "/rss.xml", "/index.xml"]
        return any(indicator in url_lower for indicator in rss_indicators)

    def discover(
        self, keywords: List[str], existing_urls: List[str]
    ) -> List[dict]:
        """通过搜索引擎发现 RSS 源"""
        all_feeds = []

        for keyword in keywords:
            query = self.search_template.format(keyword=keyword)
            logger.info(f"[SearchStrategy] Searching: {query}")
            urls = self._search_duckduckgo(query)

            for url in urls:
                is_rss = self._is_likely_rss_url(url)
                all_feeds.append({
                    "feed_url": url,
                    "discovery_query": keyword,
                    "source_strategy": self.strategy_name,
                    "reason": f'关键词 "{keyword}" 搜索发现' + ("（RSS URL）" if is_rss else "（网站，可能有 RSS）"),
                    "is_rss_url": is_rss,
                })

        # URL 精确去重
        seen = set()
        unique_feeds = []
        for feed in all_feeds:
            url = feed["feed_url"]
            if url not in seen:
                seen.add(url)
                unique_feeds.append(feed)

        return unique_feeds
