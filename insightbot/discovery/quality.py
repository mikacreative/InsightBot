"""
RSS 源质量评估模块
抓取 RSS 前 5 条内容，检查更新频率、内容量
返回 estimated_quality: high / medium / low
"""

import logging
import re
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)


def parse_rss_date(date_str: Optional[str]) -> Optional[datetime]:
    """解析 RSS 标准时间字符串"""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    return None


def extract_text_from_html(html: str) -> str:
    """从 HTML 中提取纯文本"""
    if not html:
        return ""
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class QualityScorer:
    """RSS 源质量评分器"""

    def __init__(
        self,
        max_entries_to_fetch: int = 5,
        timeout: int = 8,
    ):
        self.max_entries_to_fetch = max_entries_to_fetch
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                timeout=self.timeout,
                headers={
                    "User-Agent": (
                        "InsightBot/1.0 (RSS Quality Assessment; "
                        "+https://github.com/mikacreative/InsightBot)"
                    )
                },
                follow_redirects=True,
            )
        return self._client

    def _fetch_and_parse_feed(self, feed_url: str) -> Optional[dict]:
        """抓取并解析 RSS/Atom feed"""
        try:
            import httpx
            import xml.etree.ElementTree as ET
        except ImportError as e:
            logger.warning(f"[QualityScorer] Import error: {e}")
            return None

        try:
            client = self._get_client()
            resp = client.get(feed_url, timeout=self.timeout)
            resp.raise_for_status()
            content = resp.text
        except Exception as e:
            logger.debug(f"[QualityScorer] Failed to fetch {feed_url}: {e}")
            return None

        try:
            root = ET.fromstring(content.encode("utf-8"))
        except Exception as e:
            logger.debug(f"[QualityScorer] Failed to parse XML from {feed_url}: {e}")
            return None

        tag = root.tag.lower() if root.tag else ""
        items = []

        if "rss" in tag or "rdf" in tag:
            channel = root.find("channel") or root
            for item in channel.findall("item")[: self.max_entries_to_fetch]:
                title = self._get_text(item, "title")
                link = self._get_text(item, "link") or ""
                description = self._get_text(item, "description") or ""
                pub_date = self._get_text(item, "pubDate")
                content_el = item.find("content:encoded")
                content = content_el.text if content_el is not None else description
                items.append({
                    "title": title,
                    "link": link,
                    "description": description,
                    "content": content,
                    "pub_date": pub_date,
                })
        elif "feed" in tag or "atom" in tag:
            for entry in root.findall("entry")[: self.max_entries_to_fetch]:
                title = self._get_text(entry, "title")
                link_el = entry.find("link")
                link = link_el.get("href") if link_el is not None else ""
                summary = self._get_text(entry, "summary") or ""
                content_el = entry.find("content")
                content = self._get_text(entry, "content") or summary
                published = self._get_text(entry, "published") or self._get_text(entry, "updated")
                items.append({
                    "title": title,
                    "link": link,
                    "description": summary,
                    "content": content,
                    "pub_date": published,
                })

        if not items:
            return None

        return {"items": items, "feed_url": feed_url}

    def _get_text(self, elem, tag: str) -> str:
        """从 XML 元素获取文本"""
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        for child in elem.iter():
            if child.tag.endswith(tag) and child.text:
                return child.text.strip()
        return ""

    def _score_update_frequency(self, items: List[dict]) -> float:
        """评估更新频率得分 0-1"""
        now = datetime.now()
        recent_count = 0
        valid_dates = 0

        for item in items:
            pub_date = item.get("pub_date", "")
            if not pub_date:
                continue
            parsed = parse_rss_date(pub_date)
            if not parsed:
                continue
            valid_dates += 1
            age = now - parsed
            if age <= timedelta(days=7):
                recent_count += 1

        if valid_dates == 0:
            return 0.5

        ratio = recent_count / min(valid_dates, self.max_entries_to_fetch)
        return min(1.0, ratio * 2)

    def _score_content_quality(self, items: List[dict]) -> float:
        """评估内容质量得分 0-1"""
        if not items:
            return 0.0

        count_score = min(1.0, len(items) / self.max_entries_to_fetch)
        total_len = 0
        for item in items:
            content = item.get("content") or item.get("description") or ""
            text = extract_text_from_html(content)
            total_len += len(text)

        avg_len = total_len / len(items) if items else 0
        len_score = min(1.0, avg_len / 200)

        return 0.4 * count_score + 0.6 * len_score

    def assess_quality(self, feed_url: str) -> str:
        """评估单个 RSS 源质量"""
        try:
            feed_data = self._fetch_and_parse_feed(feed_url)
        except Exception as e:
            logger.debug(f"[QualityScorer] Error assessing {feed_url}: {e}")
            return "low"

        if not feed_data or not feed_data.get("items"):
            return "low"

        items = feed_data["items"]
        update_score = self._score_update_frequency(items)
        content_score = self._score_content_quality(items)
        total_score = 0.5 * update_score + 0.5 * content_score

        if total_score >= 0.65:
            return "high"
        elif total_score >= 0.35:
            return "medium"
        else:
            return "low"

    def assess_quality_batch(self, feed_urls: List[str]) -> Dict[str, str]:
        """批量评估 RSS 源质量"""
        results = {}
        for url in feed_urls:
            results[url] = self.assess_quality(url)
        return results

    def close(self):
        """关闭 HTTP 客户端"""
        if self._client:
            self._client.close()
            self._client = None
