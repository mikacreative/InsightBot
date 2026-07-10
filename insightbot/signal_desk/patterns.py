from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PatternContract:
    id: str
    version: str
    name: str
    user_job: str
    required_context: list[str]
    optional_context: list[str]
    default_source_pack_ids: list[str]
    default_judgement_lens_ids: list[str]
    default_output_contract_ids: list[str]
    default_quality_gate_id: str
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatternContract":
        return cls(
            id=str(data["id"]),
            version=str(data.get("version", "0.1.0")),
            name=str(data.get("name", data["id"])),
            user_job=str(data.get("user_job", "")),
            required_context=list(data.get("required_context", [])),
            optional_context=list(data.get("optional_context", [])),
            default_source_pack_ids=list(data.get("default_source_pack_ids", [])),
            default_judgement_lens_ids=list(data.get("default_judgement_lens_ids", [])),
            default_output_contract_ids=list(data.get("default_output_contract_ids", [])),
            default_quality_gate_id=str(data.get("default_quality_gate_id", "")),
            status=str(data.get("status", "draft")),
        )


@dataclass(slots=True)
class QualityGateContract:
    id: str
    requires_source: bool = True
    requires_why_it_matters: bool = True
    requires_suggested_action: bool = True
    requires_client_relevance: bool = True
    max_fallback_ratio: float = 0.2
    min_signal_count: int = 3
    max_duplicate_ratio: float = 0.25

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityGateContract":
        return cls(
            id=str(data["id"]),
            requires_source=bool(data.get("requires_source", True)),
            requires_why_it_matters=bool(data.get("requires_why_it_matters", True)),
            requires_suggested_action=bool(data.get("requires_suggested_action", True)),
            requires_client_relevance=bool(data.get("requires_client_relevance", True)),
            max_fallback_ratio=float(data.get("max_fallback_ratio", 0.2)),
            min_signal_count=int(data.get("min_signal_count", 3)),
            max_duplicate_ratio=float(data.get("max_duplicate_ratio", 0.25)),
        )


@dataclass(slots=True)
class IntentContract:
    pattern_id: str
    room_id: str
    client: str = ""
    category: str = ""
    focus_topics: list[str] = field(default_factory=list)
    output_intent: str = "client_conversation"
    time_window: str = "last_7_days"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntentContract":
        return cls(
            pattern_id=str(data["pattern_id"]),
            room_id=str(data["room_id"]),
            client=str(data.get("client", "")),
            category=str(data.get("category", "")),
            focus_topics=list(data.get("focus_topics", [])),
            output_intent=str(data.get("output_intent", "client_conversation")),
            time_window=str(data.get("time_window", "last_7_days")),
        )


_PATTERN_CONTRACTS = {
    "client_opportunity_radar": PatternContract(
        id="client_opportunity_radar",
        version="0.1.0",
        name="Client Opportunity Radar",
        user_job=(
            "Find client-relevant market signals, cases, trends, and pitchable ideas."
        ),
        required_context=["client", "category", "focus_topics", "output_intent"],
        optional_context=["time_window", "markets", "competitors"],
        default_source_pack_ids=[
            "marketing_comms_cn",
            "brand_marketing_global",
            "ai_martech",
        ],
        default_judgement_lens_ids=[
            "client_relevance",
            "pitch_potential",
            "case_inspiration",
            "strategic_implication",
        ],
        default_output_contract_ids=["signal_cards", "client_conversation_brief"],
        default_quality_gate_id="client_opportunity_radar_basic_quality",
        status="published",
    )
}

_QUALITY_GATE_CONTRACTS = {
    "client_opportunity_radar_basic_quality": QualityGateContract(
        id="client_opportunity_radar_basic_quality",
        requires_source=True,
        requires_why_it_matters=True,
        requires_suggested_action=True,
        requires_client_relevance=True,
        max_fallback_ratio=0.2,
        min_signal_count=3,
        max_duplicate_ratio=0.25,
    )
}


def get_pattern_contract(pattern_id: str) -> PatternContract:
    return deepcopy(_PATTERN_CONTRACTS[pattern_id])


def list_pattern_contracts(status: str | None = "published") -> list[PatternContract]:
    patterns = [deepcopy(pattern) for pattern in _PATTERN_CONTRACTS.values()]
    if status is None:
        return patterns
    return [pattern for pattern in patterns if pattern.status == status]


def get_quality_gate_contract(gate_id: str) -> QualityGateContract:
    return deepcopy(_QUALITY_GATE_CONTRACTS[gate_id])


def list_quality_gate_contracts() -> list[QualityGateContract]:
    return [deepcopy(gate) for gate in _QUALITY_GATE_CONTRACTS.values()]
