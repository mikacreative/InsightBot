"""
发现策略基类
所有具体策略（目录/搜索/AI）都继承此基类
"""

from abc import ABC, abstractmethod
from typing import List


class DiscoveryStrategy(ABC):
    """
    发现策略抽象基类

    方法：
        discover(keywords, existing_urls):
            执行发现，返回发现的 RSS 源列表
            每条包含：
                - feed_url: RSS 源 URL
                - discovery_query: 发现时使用的查询词/策略名
                - source_strategy: 来源策略标识
                - reason: 发现理由（可选）
    """

    @abstractmethod
    def discover(
        self, keywords: List[str], existing_urls: List[str]
    ) -> List[dict]:
        """
        执行发现

        Args:
            keywords: 关键词列表（如板块名）
            existing_urls: 已存在的 feed URL 列表（用于去重参考）

        Returns:
            List[dict]: 发现的 RSS 源列表，每条包含 feed_url, discovery_query, source_strategy
        """
        pass

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """策略名称标识"""
        pass
