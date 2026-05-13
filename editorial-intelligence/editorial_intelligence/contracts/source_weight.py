"""
Source weight and priority contract.

Defines how content sources are weighted and selected:
  official > rsshub > agent_search

Search providers are configured separately and can be switched at runtime.
"""

from dataclasses import dataclass, field
from enum import Enum


class SourceType(Enum):
    """Content source origin types, ordered by reliability priority."""

    # Direct official feeds (RSS/Atom) — highest trust, no intermediate
    OFFICIAL = "official"

    # RSSHub proxy — intermediate, subject to rate limits and availability
    RSSHUB = "rsshub"

    # Agent search (DuckDuckGo, Brave, 博查, etc.) — lowest base priority
    AGENT_SEARCH = "agent_search"


@dataclass(slots=True)
class SearchProvider:
    """
    A single search provider with its own API credentials and base URL.
    Multiple providers can be registered; selection is driven by weight and availability.
    """

    provider_id: str
    name: str
    base_url: str = ""
    api_key: str = ""
    weight: float = 1.0  # relative weight when multiple providers are available
    enabled: bool = True
    timeout_s: int = 30


@dataclass(slots=True)
class SourceWeightConfig:
    """
    Per-source-type weight multiplier.

    Applied on top of base source quality scores to produce final rankings.
    Weights are multiplicative: effective_score = base_score * source_weight
    """

    # Official RSS/Atom feeds get highest weight
    official: float = 1.0

    # RSSHub gets reduced weight due to intermediate proxy risk
    rsshub: float = 0.7

    # Agent search gets lowest weight — valuable for coverage but lower trust
    agent_search: float = 0.4

    # Search provider weights (overrides the agent_search default for specific providers)
    search_providers: dict[str, SearchProvider] = field(default_factory=dict)

    def weight_for(self, source_type: SourceType) -> float:
        return getattr(self, source_type.value)

    def weight_for_search_provider(self, provider_id: str) -> float:
        provider = self.search_providers.get(provider_id)
        if provider and provider.enabled:
            return provider.weight
        return self.agent_search  # fallback to type default


# Default global config — should be overridden per-task via editorial_policy
DEFAULT_SOURCE_WEIGHT = SourceWeightConfig()
