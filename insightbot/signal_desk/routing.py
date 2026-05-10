from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .patterns import IntentContract


DEFAULT_PATTERN_ID = "client_opportunity_radar"
DEFAULT_TIME_WINDOW = "last_7_days"
DEFAULT_OUTPUT_INTENT = "client_conversation"
DEFAULT_RESULT_MODE = "selected_signals"


@dataclass(slots=True)
class SignalDeskAccessRequest:
    text: str = ""
    pattern_id: str = ""
    room_id: str = ""
    client: str = ""
    category: str = ""
    focus_topics: list[str] = field(default_factory=list)
    time_window: str = ""
    output_intent: str = ""
    result_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalDeskAccessRequest":
        return cls(
            text=str(data.get("text", "")),
            pattern_id=str(data.get("pattern_id", "")),
            room_id=str(data.get("room_id", "")),
            client=str(data.get("client", "")),
            category=str(data.get("category", "")),
            focus_topics=list(data.get("focus_topics", [])),
            time_window=str(data.get("time_window", "")),
            output_intent=str(data.get("output_intent", "")),
            result_mode=str(data.get("result_mode", "")),
        )


@dataclass(slots=True)
class SignalDeskRoute:
    pattern_id: str
    time_window: str
    output_intent: str
    result_mode: str
    room_id: str = ""
    confidence: str = "rule_based"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_signal_desk_route(
    request: SignalDeskAccessRequest | dict[str, Any] | None,
) -> SignalDeskRoute:
    access_request = _coerce_access_request(request)
    text = access_request.text

    pattern_id, pattern_warnings = normalize_pattern_id(access_request.pattern_id, text)
    time_window, time_warnings = normalize_time_window(access_request.time_window, text)
    output_intent, intent_warnings = normalize_output_intent(
        access_request.output_intent, text
    )
    result_mode, result_warnings = normalize_result_mode(access_request.result_mode, text)

    return SignalDeskRoute(
        pattern_id=pattern_id,
        time_window=time_window,
        output_intent=output_intent,
        result_mode=result_mode,
        room_id=access_request.room_id,
        warnings=[
            *pattern_warnings,
            *time_warnings,
            *intent_warnings,
            *result_warnings,
        ],
    )


def route_to_intent_contract(
    route: SignalDeskRoute, *, room_id: str | None = None
) -> IntentContract:
    return IntentContract(
        pattern_id=route.pattern_id,
        room_id=room_id if room_id is not None else route.room_id,
        output_intent=route.output_intent,
        time_window=route.time_window,
    )


def normalize_result_mode(value: str = "", text: str = "") -> tuple[str, list[str]]:
    return _normalize(
        value=value,
        text=text,
        default=DEFAULT_RESULT_MODE,
        field_name="result_mode",
        explicit_values={
            "raw_feed": "raw_feed",
            "brief_output": "brief_output",
            "selected_signals": "selected_signals",
        },
        text_rules=[
            ("raw_feed", ["raw feed", "source feed", "raw", "all", "全部", "全量", "原始"]),
            (
                "brief_output",
                ["client brief", "proposal brief", "brief", "简报", "日报"],
            ),
            (
                "selected_signals",
                ["selected", "curated", "signal", "精选"],
            ),
        ],
    )


def normalize_output_intent(value: str = "", text: str = "") -> tuple[str, list[str]]:
    return _normalize(
        value=value,
        text=text,
        default=DEFAULT_OUTPUT_INTENT,
        field_name="output_intent",
        explicit_values={
            "client_conversation": "client_conversation",
            "proposal_angle": "proposal_angle",
            "internal_inspiration": "internal_inspiration",
            "trend_observation": "trend_observation",
        },
        text_rules=[
            ("proposal_angle", ["proposal", "pitch", "提案", "销售角度"]),
            ("internal_inspiration", ["inspiration", "灵感", "案例"]),
            ("trend_observation", ["trend", "趋势", "观察"]),
        ],
    )


def normalize_time_window(value: str = "", text: str = "") -> tuple[str, list[str]]:
    return _normalize(
        value=value,
        text=text,
        default=DEFAULT_TIME_WINDOW,
        field_name="time_window",
        explicit_values={
            "last_7_days": "last_7_days",
            "last_14_days": "last_14_days",
            "last_30_days": "last_30_days",
        },
        text_rules=[
            ("last_30_days", ["30 days", "30天", "past month", "last month"]),
            ("last_14_days", ["14 days", "14天", "两周"]),
            ("last_7_days", ["7 days", "7天", "一周", "week"]),
        ],
    )


def normalize_pattern_id(value: str = "", text: str = "") -> tuple[str, list[str]]:
    return _normalize(
        value=value,
        text=text,
        default=DEFAULT_PATTERN_ID,
        field_name="pattern_id",
        explicit_values={
            "client_opportunity_radar": "client_opportunity_radar",
        },
        text_rules=[
            (
                "client_opportunity_radar",
                ["client radar", "opportunity radar", "client opportunity"],
            ),
        ],
    )


def _coerce_access_request(
    request: SignalDeskAccessRequest | dict[str, Any] | None,
) -> SignalDeskAccessRequest:
    if request is None:
        return SignalDeskAccessRequest()
    if isinstance(request, SignalDeskAccessRequest):
        return request
    return SignalDeskAccessRequest.from_dict(request)


def _normalize(
    *,
    value: str,
    text: str,
    default: str,
    field_name: str,
    explicit_values: dict[str, str],
    text_rules: list[tuple[str, list[str]]],
) -> tuple[str, list[str]]:
    explicit_value = value.strip()
    if explicit_value:
        normalized_value = explicit_value.lower().replace("-", "_").replace(" ", "_")
        if normalized_value in explicit_values:
            return explicit_values[normalized_value], []
        return (
            default,
            [f"Unknown {field_name} '{explicit_value}'; using {default}."],
        )

    normalized_text = text.lower()
    for resolved_value, needles in text_rules:
        if any(needle in normalized_text for needle in needles):
            return resolved_value, []
    return default, []
