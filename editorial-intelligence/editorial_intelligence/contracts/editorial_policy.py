from dataclasses import dataclass, field


@dataclass(slots=True)
class EditorialPolicy:
    shortlist_size: int = 8
    selection_rules: list[str] = field(default_factory=list)
    section_rules: dict[str, str] = field(default_factory=dict)
    dedupe_rules: list[str] = field(default_factory=list)
    tone: str = "concise"
    citation_style: str = "inline"
    quality_checks: list[str] = field(default_factory=list)
