"""Source adapters."""

from .base import NormalizedSignal, SourceAdapter
from .rss import RSSAdapter
from .search import SearchAdapter

__all__ = [
    "NormalizedSignal",
    "SourceAdapter",
    "RSSAdapter",
    "SearchAdapter",
]
