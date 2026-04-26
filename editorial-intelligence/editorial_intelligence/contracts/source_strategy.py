from dataclasses import dataclass, field


@dataclass(slots=True)
class SourceStrategy:
    primary_sources: list[str] = field(default_factory=list)
    fallback_sources: list[str] = field(default_factory=list)
    search_enabled: bool = True
    platform_enabled: bool = False
    max_explore_rounds: int = 1
    coverage_threshold: float = 0.7
    freshness_threshold_hours: int = 24
    source_constraints: dict[str, str] = field(default_factory=dict)
