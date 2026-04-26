from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BriefingResult:
    ok: bool
    source_summary: dict[str, Any] = field(default_factory=dict)
    candidate_pool: list[dict[str, Any]] = field(default_factory=list)
    shortlist: list[dict[str, Any]] = field(default_factory=list)
    section_assignments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    final_brief: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
