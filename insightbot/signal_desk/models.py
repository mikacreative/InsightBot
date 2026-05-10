from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class BriefingRoom:
    id: str
    name: str
    topic: str
    source_pack_ids: list[str]
    editorial_preset_id: str
    judgement_lens_ids: list[str]
    channels: list[str]
    schedule: dict[str, int]
    enabled: bool = False
    use_case_template_id: str = "client_opportunity_radar"
    audience: str = "senior account and strategy team"
    focus_areas: list[str] = field(default_factory=list)
    client_context: dict[str, Any] = field(default_factory=dict)
    compiled_task_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.compiled_task_id:
            self.compiled_task_id = f"room_{self.id}"
        now = _utc_now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BriefingRoom":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            topic=str(data["topic"]),
            source_pack_ids=list(data.get("source_pack_ids", [])),
            editorial_preset_id=str(data.get("editorial_preset_id", "client_opportunity_radar")),
            judgement_lens_ids=list(data.get("judgement_lens_ids", [])),
            channels=list(data.get("channels", [])),
            schedule=dict(data.get("schedule", {"hour": 8, "minute": 0})),
            enabled=bool(data.get("enabled", False)),
            use_case_template_id=str(data.get("use_case_template_id", "client_opportunity_radar")),
            audience=str(data.get("audience", "senior account and strategy team")),
            focus_areas=list(data.get("focus_areas", [])),
            client_context=dict(data.get("client_context", {})),
            compiled_task_id=str(data.get("compiled_task_id", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass(slots=True)
class SignalItem:
    id: str
    room_id: str
    run_id: str
    what_happened: str
    why_it_matters: str
    client_relevance: str
    suggested_action: str
    judgement_lens: list[str]
    source: dict[str, str]
    confidence: str = "medium"
    save_tags: list[str] = field(default_factory=list)
    raw_candidate_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SavedSignal:
    id: str
    signal: dict[str, Any]
    room_id: str
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FeedbackRecord:
    id: str
    signal_id: str
    room_id: str
    action: str
    note: str = ""
    pattern_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BriefArtifact:
    id: str
    room_id: str
    title: str
    output_intent: str
    source_signal_ids: list[str]
    markdown: str
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
