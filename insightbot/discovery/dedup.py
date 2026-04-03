"""
三层去重模块
- L1: URL 精确去重
- L2: 域名去重（同域名只保留一个）
- L3: 内容相似度兜底（Jaccard similarity, threshold=0.5）
"""

import logging
import re
import urllib.parse
from typing import List, Set, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

JACCARD_THRESHOLD = 0.5


def normalize_url(url: str) -> str:
    """URL 规范化"""
    url = url.strip().lower()
    if url.startswith("http://"):
        url = "https://" + url[7:]
    elif not url.startswith("https://"):
        url = "https://" + url

    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")

    return urllib.parse.urlunparse((parsed.scheme, netloc, path, parsed.params, parsed.query, ""))


def extract_domain(url: str) -> str:
    """提取域名"""
    try:
        parsed = urlparse(normalize_url(url))
        return parsed.netloc
    except Exception:
        return ""


def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    """计算两个集合的 Jaccard 相似度"""
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def tokenize_content(content: str) -> Set[str]:
    """将内容分词为词集合"""
    if not content:
        return set()
    chinese_words = re.findall(r"[\u4e00-\u9fff]{2,4}", content)
    english_words = re.findall(r"[a-zA-Z]{3,}", content.lower())
    tokens = set()
    for word in chinese_words + english_words:
        if len(word) >= 2:
            tokens.add(word)
    return tokens


class Deduplicator:
    """
    三层去重器
    L1 - URL 精确去重
    L2 - 域名去重（同域名只保留一个）
    L3 - 内容相似度（Jaccard, threshold=0.5）
    """

    def __init__(self, existing_feeds: List[dict], jaccard_threshold: float = JACCARD_THRESHOLD):
        self.existing_urls: Set[str] = set()
        self.existing_domains: Set[str] = set()
        self.jaccard_threshold = jaccard_threshold

        for feed in existing_feeds:
            url = feed.get("feed_url", "")
            if url:
                normalized = normalize_url(url)
                self.existing_urls.add(normalized)
                self.existing_domains.add(extract_domain(url))

        logger.info(
            f"[Deduplicator] Initialized with {len(self.existing_urls)} existing URLs, "
            f"{len(self.existing_domains)} domains"
        )

    def add_existing(self, urls: List[str]):
        """添加已存在的 URL 到去重池"""
        for url in urls:
            if url:
                normalized = normalize_url(url)
                self.existing_urls.add(normalized)
                self.existing_domains.add(extract_domain(url))

    def deduplicate(self, feeds: List[dict]) -> List[dict]:
        """执行三层去重"""
        if not feeds:
            return []

        # L1: URL 精确去重
        result = []
        seen_urls: Set[str] = set()

        for feed in feeds:
            url = feed.get("feed_url", "")
            if not url:
                continue

            normalized = normalize_url(url)
            if normalized in self.existing_urls or normalized in seen_urls:
                logger.debug(f"[Dedup L1] Skipping duplicate URL: {url}")
                continue

            seen_urls.add(normalized)
            result.append(feed)

        logger.info(f"[Dedup] After L1 (URL dedup): {len(result)}/{len(feeds)}")

        # L2: 域名去重
        result = self._deduplicate_by_domain(result)
        logger.info(f"[Dedup] After L2 (domain dedup): {len(result)}")

        return result

    def _deduplicate_by_domain(self, feeds: List[dict]) -> List[dict]:
        """L2: 同域名只保留一个（保留第一个）"""
        seen_domains: Set[str] = set()
        result = []

        for feed in feeds:
            url = feed.get("feed_url", "")
            domain = extract_domain(url)

            if not domain:
                result.append(feed)
                continue

            if domain in seen_domains:
                logger.debug(f"[Dedup L2] Skipping duplicate domain: {domain} ({url})")
                continue

            seen_domains.add(domain)
            result.append(feed)

        return result

    def deduplicate_with_content(
        self,
        feeds: List[dict],
        content_map: Optional[dict] = None,
    ) -> List[dict]:
        """L3: 内容相似度去重"""
        feeds = self.deduplicate(feeds)

        if not content_map:
            return feeds

        result = []
        content_sets: List[tuple] = []

        for feed in feeds:
            url = feed.get("feed_url", "")
            content = content_map.get(url, "")
            tokens = tokenize_content(content)
            content_sets.append((feed, tokens))

        for i, (feed_i, tokens_i) in enumerate(content_sets):
            if not tokens_i:
                result.append(feed_i)
                continue

            is_duplicate = False
            for _, tokens_j in content_sets[:i]:
                if not tokens_j:
                    continue
                sim = jaccard_similarity(tokens_i, tokens_j)
                if sim >= self.jaccard_threshold:
                    logger.debug(f"[Dedup L3] Jaccard {sim:.2f} duplicate, skipping")
                    is_duplicate = True
                    break

            if not is_duplicate:
                result.append(feed_i)

        logger.info(f"[Dedup] After L3 (content similarity): {len(result)}")
        return result
