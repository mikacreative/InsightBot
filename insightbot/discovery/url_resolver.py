"""
URL 解析器：用户输入网站 URL → RSSHub 自动 RSS 化

策略：
1. 先尝试 /rss/:url — RSSHub 原生 RSS autodiscovery
2. 失败则尝试 /generate/:url — RSSHub puppeteer 通用页面抓取
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_RSSHUB_BASE = "https://rsshub.app"


@dataclass
class ResolveResult:
    """URL 解析结果"""
    status: str                        # "success" | "multi_candidates" | "failed"
    feed_url: Optional[str] = None     # 成功后可用的 feed URL
    reason: Optional[str] = None       # 失败原因
    candidates: list[str] = field(default_factory=list)   # 多候选时


class UrlResolver:
    """
    用户输入 URL → 尝试 RSSHub 转为可抓取 RSS
    """

    def __init__(self, rsshub_base: str = DEFAULT_RSSHUB_BASE, timeout: int = 20):
        self.rsshub_base = rsshub_base.rstrip("/")
        self.timeout = timeout

    def resolve(self, url: str) -> ResolveResult:
        """
        主入口：解析用户 URL，返回 ResolveResult
        """
        normalized = url.strip().rstrip("/")
        if not normalized.startswith("http"):
            return ResolveResult(
                status="failed",
                reason="请输入完整的 URL，以 http:// 或 https:// 开头",
            )

        # Step 1: 尝试原生 RSS autodiscovery
        logger.info(f"[UrlResolver] Trying /rss/: {normalized}")
        result = self._try_feed(f"{self.rsshub_base}/rss/{normalized}")
        if result.status == "success":
            logger.info(f"[UrlResolver] /rss/ succeeded: {result.feed_url}")
            return result

        # Step 2: 尝试 RSSHub generate
        logger.info(f"[UrlResolver] Trying /generate/: {normalized}")
        result = self._try_feed(f"{self.rsshub_base}/generate/{normalized}")
        logger.info(f"[UrlResolver] /generate/ result: {result.status} - {result.reason or result.feed_url}")
        return result

    def _try_feed(self, feed_url: str) -> ResolveResult:
        """尝试获取 feed URL，验证是有效 RSS/Atom"""
        try:
            import httpx
        except ImportError:
            return ResolveResult(
                status="failed",
                reason="httpx 未安装，请运行: pip install httpx",
            )

        try:
            response = httpx.get(
                feed_url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "InsightBot/1.0"},
            )
        except Exception as e:
            return ResolveResult(status="failed", reason=f"请求失败: {e}")

        if response.status_code != 200:
            return ResolveResult(
                status="failed",
                reason=f"RSSHub 返回 HTTP {response.status_code}",
            )

        # 验证是有效 RSS/Atom
        try:
            import feedparser
            feed = feedparser.parse(response.text)
            if feed.bozo:
                return ResolveResult(
                    status="failed",
                    reason="RSSHub 返回内容不是有效 RSS/Atom",
                )
            return ResolveResult(status="success", feed_url=feed_url)
        except Exception as e:
            return ResolveResult(
                status="failed",
                reason=f"RSS 解析失败: {e}",
            )


# 独立函数接口
def resolve_url(url: str, rsshub_base: str = DEFAULT_RSSHUB_BASE) -> ResolveResult:
    resolver = UrlResolver(rsshub_base=rsshub_base)
    return resolver.resolve(url)
