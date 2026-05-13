from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class NormalizedSignal:
    source_type: str
    source_id: str
    title: str
    summary: str
    url: str
    published_at: str = ""
    signals: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    def collect(self, **kwargs: Any) -> list[NormalizedSignal]:
        """Collect and normalize source signals."""
