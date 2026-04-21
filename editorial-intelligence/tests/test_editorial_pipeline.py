"""
Tests for editorial pipeline and source weight ranking.
"""

import pytest

from editorial_intelligence.adapters import NormalizedSignal, RSSAdapter, SearchAdapter
from editorial_intelligence.contracts import SourceWeightConfig, SearchProvider
from editorial_intelligence.workflows.editorial_pipeline import (
    WeightedSignalPool,
    _recency_score,
    _classify_signal,
)


class TestWeightedSignalPool:
    """Tests for in-memory weighted ranking and deduplication."""

    def test_deduplicate_removes_duplicate_urls(self):
        pool = WeightedSignalPool()
        pool.add_signals([
            _make_signal("https://example.com/1", "official", "2026-04-21T10:00:00"),
            _make_signal("https://example.com/1", "official", "2026-04-21T10:00:00"),
            _make_signal("https://example.com/2", "agent_search", ""),
        ])
        pool.deduplicate()
        assert len(pool.signals) == 2

    def test_rank_official_higher_than_agent_search(self):
        config = SourceWeightConfig(official=1.0, agent_search=0.4)
        pool = WeightedSignalPool(weight_config=config)
        pool.add_signals([
            _make_signal("https://a.com", "official", "2026-04-21T10:00:00"),
            _make_signal("https://b.com", "agent_search", "2026-04-21T10:00:00"),
        ])
        pool.rank()
        # official has higher effective weight
        official_score = pool.signals[0].signals["_rank_score"]
        search_score = pool.signals[1].signals["_rank_score"]
        assert official_score > search_score

    def test_top_n_returns_n_signals(self):
        pool = WeightedSignalPool()
        for i in range(10):
            pool.add_signals([_make_signal(f"https://e{i}.com", "official", "2026-04-21T10:00:00")])
        pool.rank()
        top5 = pool.top_n(5)
        assert len(top5) == 5


class TestRecencyScore:
    def test_recent_signal_scores_high(self):
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        assert _recency_score(recent) > 0.9

    def test_old_signal_scores_low(self):
        # Naive datetime (no TZ) gets caught by exception handler → 0.5
        # For truly old timestamps, use ISO format with TZ: "2020-01-01T00:00:00+00:00"
        old = "2020-01-01T00:00:00+00:00"
        assert _recency_score(old) < 0.2

    def test_missing_published_at_returns_05(self):
        assert _recency_score("") == 0.5


class TestClassifySignal:
    def test_classifies_by_keyword(self):
        sections = {"tool": "AI,ChatGPT,Claude", "industry": "营销,增长"}
        signal = {"title": "ChatGPT 发布新功能", "summary": ""}
        assert _classify_signal(signal, sections) == "tool"

    def test_falls_back_to_other(self):
        signal = {"title": "Some random news", "summary": ""}
        assert _classify_signal(signal, {}) == "other"


class TestRSSAdapter:
    def test_collect_with_empty_feeds_returns_empty(self):
        adapter = RSSAdapter()
        result = adapter.collect(feeds=[])
        assert result == []

    def test_collect_with_none_returns_empty(self):
        adapter = RSSAdapter()
        result = adapter.collect(feeds=None)
        assert result == []


def _make_signal(url: str, source_type: str, published_at: str) -> NormalizedSignal:
    return NormalizedSignal(
        source_type=source_type,
        source_id="test",
        title=f"Signal from {url}",
        summary="test summary",
        url=url,
        published_at=published_at,
        signals={},
        raw={},
    )
