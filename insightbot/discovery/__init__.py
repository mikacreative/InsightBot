"""
InsightBot 订阅源发现模块
提供多种策略发现新的 RSS 订阅源：目录扫描、搜索引擎、AI 推荐
"""

from insightbot.discovery.base import DiscoveryStrategy
from insightbot.discovery.directory import DirectoryStrategy
from insightbot.discovery.search import SearchStrategy
from insightbot.discovery.ai import AIStrategy

__all__ = [
    "DiscoveryStrategy",
    "DirectoryStrategy",
    "SearchStrategy",
    "AIStrategy",
]
