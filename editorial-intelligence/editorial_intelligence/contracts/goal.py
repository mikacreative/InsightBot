from dataclasses import dataclass, field


@dataclass(slots=True)
class BriefingGoal:
    topic: str
    audience: str = ""
    brief_type: str = "daily_brief"
    focus_areas: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    time_window: str = "24h"
    quality_bar: str = "production"
