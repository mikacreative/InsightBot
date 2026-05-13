"""
Editorial pipeline — collects, ranks, deduplicates, and produces a briefing.

Workflow:
  1. Collect from official RSS/Atom feeds
  2. Collect from agent search (multi-provider)
  3. Merge into a weighted candidate pool
  4. Deduplicate by URL
  5. Rank by source weight * recency score
  6. Shortlist top candidates
  7. Assign to sections
  8. Emit diagnostics and final brief
"""

import logging
from datetime import datetime, timezone
from typing import Any

from ..adapters import NormalizedSignal, RSSAdapter, SearchAdapter
from ..contracts.briefing_result import BriefingResult
from ..contracts.source_strategy import SourceStrategy
from ..contracts.source_weight import DEFAULT_SOURCE_WEIGHT, SourceWeightConfig

logger = logging.getLogger(__name__)


def run_editorial_pipeline(*, context: dict) -> BriefingResult:
    """
    Execute the full editorial briefing pipeline.

    Args:
        context: Must contain goal, source_strategy, editorial_policy.
    """
    goal: dict = context.get("goal", {})
    source_strategy: SourceStrategy = context.get("source_strategy", SourceStrategy())
    editorial_policy: dict = context.get("editorial_policy", {})
    source_weight_config: SourceWeightConfig = context.get(
        "source_weight_config", DEFAULT_SOURCE_WEIGHT
    )
    logger.info(f"Starting editorial pipeline for goal: {goal.get('topic', 'unknown')}")

    # ── Step 1: Collect from RSS ────────────────────────────────────────────
    rss_signals: list[NormalizedSignal] = []
    if source_strategy.primary_sources:
        rss_adapter = RSSAdapter()
        rss_signals = rss_adapter.collect(feeds=source_strategy.primary_sources)

    # ── Step 2: Collect from agent search ───────────────────────────────────
    search_signals: list[NormalizedSignal] = []
    if source_strategy.search_enabled:
        search_adapter = SearchAdapter(providers_config=source_weight_config)
        queries = _extract_queries(goal, source_strategy)
        if queries:
            search_signals = search_adapter.collect(queries=queries)

    # ── Step 3: Merge pool ───────────────────────────────────────────────────
    pool = WeightedSignalPool(source_weight_config)
    pool.add_signals(rss_signals)
    pool.add_signals(search_signals)

    # ── Step 4: Deduplicate by URL ───────────────────────────────────────────
    pool.deduplicate()

    # ── Step 5: Rank ──────────────────────────────────────────────────────────
    pool.rank()

    # ── Step 6: Shortlist ────────────────────────────────────────────────────
    shortlist_size = editorial_policy.get("shortlist_size", 8)
    shortlist = pool.top_n(shortlist_size)

    # ── Step 7: Assign to sections ──────────────────────────────────────────
    sections = _assign_sections(shortlist, editorial_policy)

    # ── Step 8: Build final brief ───────────────────────────────────────────
    final_markdown = _build_markdown(goal, shortlist, sections)

    diagnostics = {
        "coverage_gaps": [],
        "source_failures": [],
        "source_counts": {
            "official": len(rss_signals),
            "agent_search": len(search_signals),
            "after_dedup": len(pool.signals),
            "shortlisted": len(shortlist),
        },
    }

    return BriefingResult(
        ok=True,
        source_summary={"total_candidates": len(pool.signals)},
        candidate_pool=[_signal_to_dict(s) for s in pool.signals],
        shortlist=[_signal_to_dict(s) for s in shortlist],
        section_assignments=sections,
        final_brief={"markdown": final_markdown},
        diagnostics=diagnostics,
    )


# ────────────────────────────────────────────────────────────────────────────
# WeightedSignalPool
# ────────────────────────────────────────────────────────────────────────────

class WeightedSignalPool:
    """
    In-memory pool of NormalizedSignals with weight-based ranking.
    """

    def __init__(self, weight_config: SourceWeightConfig | None = None):
        self.weight_config = weight_config or DEFAULT_SOURCE_WEIGHT
        self.signals: list[NormalizedSignal] = []

    def add_signals(self, signals: list[NormalizedSignal]) -> None:
        self.signals.extend(signals)

    def deduplicate(self) -> None:
        seen_urls: set[str] = set()
        unique: list[NormalizedSignal] = []
        for s in self.signals:
            if s.url and s.url not in seen_urls:
                seen_urls.add(s.url)
                unique.append(s)
        logger.debug(f"Dedup: {len(self.signals)} → {len(unique)}")
        self.signals = unique

    def rank(self) -> None:
        """Sort signals by effective_weight * recency_score descending."""
        for signal in self.signals:
            w = self._effective_weight(signal)
            recency = _recency_score(signal.published_at)
            signal.signals["_rank_score"] = w * recency
        self.signals.sort(key=lambda s: s.signals.get("_rank_score", 0), reverse=True)

    def top_n(self, n: int) -> list[NormalizedSignal]:
        return self.signals[:n]

    def _effective_weight(self, signal: NormalizedSignal) -> float:
        source_type = signal.source_type
        if source_type == "official":
            base = self.weight_config.official
        elif source_type == "rsshub":
            base = self.weight_config.rsshub
        elif source_type == "agent_search":
            provider_id = signal.signals.get("provider", "")
            base = self.weight_config.weight_for_search_provider(provider_id)
        else:
            base = 0.5
        return base


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _extract_queries(goal: dict, strategy: SourceStrategy) -> list[str]:
    """Extract search queries from goal or strategy."""
    queries = goal.get("queries", [])
    if not queries and strategy.source_constraints.get("queries"):
        queries = strategy.source_constraints["queries"]
    if not queries:
        # Fall back to topic as a single query
        topic = goal.get("topic", "")
        if topic:
            queries = [topic]
    return queries


def _assign_sections(
    shortlist: list[NormalizedSignal], policy: dict
) -> dict[str, list[dict]]:
    """Assign shortlisted signals to sections based on policy rules."""
    sections: dict[str, list[dict]] = {
        "hot": [],
        "industry": [],
        "tool": [],
        "other": [],
    }
    section_rules: dict[str, str] = policy.get("section_rules", {})

    for signal in shortlist:
        d = _signal_to_dict(signal)
        section = _classify_signal(d, section_rules)
        sections[section].append(d)

    return {k: v for k, v in sections.items() if v}


def _classify_signal(signal: dict, rules: dict[str, str]) -> str:
    title_lower = signal.get("title", "").lower()
    summary_lower = signal.get("summary", "").lower()
    text = title_lower + " " + summary_lower

    for section, keywords in rules.items():
        if any(kw.lower() in text for kw in keywords.split(",")):
            return section
    return "other"


def _recency_score(published_at: str) -> float:
    """Simple recency score: 1.0 for today, decays exponentially older."""
    if not published_at:
        return 0.5
    try:
        dt = datetime.fromisoformat(published_at)
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return max(0.1, 1.0 / (1.0 + age_hours / 24))
    except Exception:
        return 0.5


def _build_markdown(goal: dict, shortlist: list[NormalizedSignal], sections: dict[str, list[dict]]) -> str:
    topic = goal.get("topic", "未知主题")
    lines = [f"# {topic}", ""]

    for section_name, items in sections.items():
        if not items:
            continue
        lines.append(f"## {section_name.upper()}")
        for item in items:
            title = item.get("title", "无标题")
            url = item.get("url", "")
            summary = item.get("summary", "")
            source = item.get("source_type", "")
            lines.append(f"- **{title}** ({source})")
            if summary:
                lines.append(f"  {summary[:120]}...")
            if url:
                lines.append(f"  {url}")
        lines.append("")

    return "\n".join(lines)


def _signal_to_dict(signal: NormalizedSignal) -> dict[str, Any]:
    return {
        "source_type": signal.source_type,
        "source_id": signal.source_id,
        "title": signal.title,
        "summary": signal.summary,
        "url": signal.url,
        "published_at": signal.published_at,
        "signals": signal.signals,
    }
