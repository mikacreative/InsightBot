"""
URL 解析器：用户输入网站 URL → 探测是否有原生 RSS/Atom 源

策略：
1. 抓取用户 URL 的 HTML，查找 <link rel="alternate" type="application/rss+xml"> 自动发现
2. 同时探测常见 feed 路径：/feed, /rss, /atom.xml 等
3. 验证找到的 URL 是有效 RSS/Atom 后返回
"""

import logging
import re
import warnings

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    pass
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger(__name__)


# 常见 feed 路径探测列表（按优先级排序）
COMMON_FEED_PATHS = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss/",
    "/atom.xml",
    "/feed.xml",
    "/rss.xml",
    "/index.xml",
    "/blog/feed",
    "/blog/feed/",
    "/feed/rss",
    "/rss/feed",
    "/posts/feed",
    "/articles/feed",
]


@dataclass
class ResolveResult:
    """URL 解析结果"""
    status: str                        # "success" | "multi_candidates" | "failed"
    feed_url: Optional[str] = None     # 成功后可用的 feed URL
    reason: Optional[str] = None       # 失败原因
    candidates: list[str] = field(default_factory=list)   # 多候选时


class UrlResolver:
    """
    用户输入 URL → 探测原生 RSS/Atom 源
    不依赖 RSSHub，直接探测目标站点的 feed
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def resolve(self, url: str) -> ResolveResult:
        """
        主入口：解析用户 URL，尝试找到 RSS/Atom 源
        """
        normalized = url.strip().rstrip("/")
        if not normalized.startswith("http"):
            return ResolveResult(
                status="failed",
                reason="请输入完整的 URL，以 http:// 或 https:// 开头",
            )

        logger.info(f"[UrlResolver] Resolving: {normalized}")

        # Step 1: HTML autodiscovery — 抓取页面，查找 <link rel="alternate" type="application/rss+xml">
        discovered = self._discover_from_html(normalized)
        if discovered:
            if len(discovered) == 1:
                if self._validate_feed(discovered[0]):
                    return ResolveResult(status="success", feed_url=discovered[0])
            else:
                # 多候选，找能验证的
                for cand in discovered:
                    if self._validate_feed(cand):
                        return ResolveResult(status="success", feed_url=cand)
                # 都没验证通过，返回第一个
                if self._validate_feed(discovered[0]):
                    return ResolveResult(status="success", feed_url=discovered[0])
                return ResolveResult(
                    status="multi_candidates",
                    candidates=discovered,
                    reason=f"找到 {len(discovered)} 个候选地址",
                )

        # Step 2: 探测常见 feed 路径
        base_url = self._get_base_url(normalized)
        for path in COMMON_FEED_PATHS:
            feed_url = base_url + path
            if self._validate_feed(feed_url):
                logger.info(f"[UrlResolver] Found via path probe: {feed_url}")
                return ResolveResult(status="success", feed_url=feed_url)

        return ResolveResult(
            status="failed",
            reason="该网站没有找到 RSS/Atom 源，或站点不支持 RSS",
        )

    def _get_base_url(self, url: str) -> str:
        """从完整 URL 提取 base（协议+域名）"""
        parsed = url.split("://", 1)
        scheme = parsed[0] + "://"
        host_part = parsed[1] if len(parsed) > 1 else ""
        # 取第一个路径段之前的部分
        if "/" in host_part:
            base = scheme + host_part.split("/")[0]
        else:
            base = scheme + host_part
        return base

    def _discover_from_html(self, url: str) -> List[str]:
        """抓取 HTML，查找 RSS/Atom autodiscovery link"""
        try:
            import httpx
        except ImportError:
            logger.warning("[UrlResolver] httpx not installed")
            return []

        try:
            response = httpx.get(
                url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; InsightBot/1.0; +https://github.com/mikacreative/InsightBot)",
                },
            )
        except Exception as e:
            logger.warning(f"[UrlResolver] Failed to fetch {url}: {e}")
            return []

        if response.status_code != 200:
            return []

        html = response.text

        # 匹配 <link rel="alternate" type="application/rss+xml" href="...">
        # 和 <link rel="alternate" type="application/atom+xml" href="...">
        feed_types = [
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
        ]
        type_pattern = "|".join(re.escape(t) for t in feed_types)

        pattern = re.compile(
            r'<link[^>]+(?:rel=["\']alternate["\'][^>]+href=["\']([^"\']+)["\'][^>]+type=["\'](' + type_pattern + ')["\']|'
            r'type=["\'](' + type_pattern + r')["\'][^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']alternate["\'])',
            re.IGNORECASE,
        )

        feeds = []
        for match in pattern.finditer(html):
            # 两个捕获组：group(1) 或 group(4) 是 href
            feed_url = match.group(1) or match.group(4)
            if feed_url and feed_url.startswith("http"):
                feeds.append(feed_url.strip())

        # 也尝试简单的正则匹配
        simple_pattern = re.compile(
            r'href=["\']([^"\']*\/feed[^"\']*)["\']',
            re.IGNORECASE,
        )
        for match in simple_pattern.finditer(html):
            feed_url = match.group(1)
            if feed_url and feed_url.startswith("http") and feed_url not in feeds:
                feeds.append(feed_url.strip())

        logger.info(f"[UrlResolver] Autodiscovery found {len(feeds)} feeds: {feeds}")
        return feeds

    def _validate_feed(self, feed_url: str) -> bool:
        """验证 URL 是否是有效的 RSS/Atom"""
        try:
            import httpx
            import feedparser
        except ImportError:
            return False

        try:
            response = httpx.get(
                feed_url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; InsightBot/1.0)",
                },
                verify=False,  # 跳过 SSL 证书验证（某些站点证书链不完整）
            )
            if response.status_code != 200:
                return False

            feed = feedparser.parse(response.text)
            # bozo 为 True 但有 entries 也不算失败（某些 RSS 格式不标准但可用）
            if feed.bozo and not feed.entries:
                return False
            return bool(feed.entries or feed.feed)
        except Exception as e:
            logger.warning(f"[UrlResolver] Feed validation failed for {feed_url}: {e}")
            return False


# 独立函数接口
def resolve_url(url: str) -> ResolveResult:
    resolver = UrlResolver()
    return resolver.resolve(url)
