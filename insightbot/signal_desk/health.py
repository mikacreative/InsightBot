from __future__ import annotations

from typing import Any, Iterable


NEGATIVE_FEEDBACK_ACTIONS = {"not_relevant", "too_shallow", "already_known"}
POSITIVE_FEEDBACK_ACTIONS = {
    "useful",
    "good_for_pitch",
    "good_for_client",
    "need_more_like_this",
}


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _matches_room(item: Any, room_id: str) -> bool:
    item_room_id = _get_value(item, "room_id")
    return item_room_id in (None, "", room_id)


def _current_room_items(items: Iterable[Any], room_id: str) -> list[Any]:
    return [item for item in items if _get_value(item, "room_id") == room_id]


def _current_room_latest_signals(latest_signals: Iterable[Any] | None, room_id: str) -> list[Any]:
    if latest_signals is None:
        return []
    return [signal for signal in latest_signals if _matches_room(signal, room_id)]


def _is_fallback_signal(signal: Any) -> bool:
    confidence = str(_get_value(signal, "confidence", "")).lower()
    save_tags = {str(tag).lower() for tag in (_get_value(signal, "save_tags", []) or [])}
    judgement_lens = {
        str(lens).lower() for lens in (_get_value(signal, "judgement_lens", []) or [])
    }

    return (confidence == "low" and "fallback" in save_tags) or "manual_review" in judgement_lens


def _build_recommendations(
    status: str,
    saved_count: int,
    fallback_signal_count: int,
    negative_feedback_count: int,
) -> list[str]:
    if status == "no_data":
        return ["No pattern data yet. Run this room and review the first signal cards."]

    recommendations = []
    if fallback_signal_count > 0:
        recommendations.append("Review fallback cards and tighten source packs or judgement lenses.")
    if negative_feedback_count > 0:
        recommendations.append("Inspect negative feedback and adjust pattern context before scaling.")
    if saved_count == 0:
        recommendations.append("Save useful signals so the pattern has positive examples.")
    if status == "healthy":
        recommendations.append("Pattern is healthy. Keep collecting examples and feedback.")
    return recommendations


def build_pattern_health_summary(
    room: Any,
    saved_signals: Iterable[Any],
    feedback_records: Iterable[Any],
    latest_signals: Iterable[Any] | None = None,
) -> dict[str, Any]:
    room_id = str(_get_value(room, "id"))
    pattern_id = str(_get_value(room, "use_case_template_id"))

    room_saved_signals = _current_room_items(saved_signals, room_id)
    room_feedback_records = _current_room_items(feedback_records, room_id)
    room_latest_signals = _current_room_latest_signals(latest_signals, room_id)

    saved_count = len(room_saved_signals)
    feedback_count = len(room_feedback_records)
    latest_signal_count = len(room_latest_signals)
    fallback_signal_count = sum(1 for signal in room_latest_signals if _is_fallback_signal(signal))
    negative_feedback_count = sum(
        1
        for record in room_feedback_records
        if str(_get_value(record, "action", "")) in NEGATIVE_FEEDBACK_ACTIONS
    )
    positive_feedback_count = sum(
        1
        for record in room_feedback_records
        if str(_get_value(record, "action", "")) in POSITIVE_FEEDBACK_ACTIONS
    )

    if saved_count == 0 and feedback_count == 0 and latest_signal_count == 0:
        status = "no_data"
    elif fallback_signal_count > 0 or negative_feedback_count > 0:
        status = "needs_attention"
    elif saved_count > 0:
        status = "healthy"
    else:
        status = "needs_attention"

    return {
        "room_id": room_id,
        "pattern_id": pattern_id,
        "status": status,
        "saved_count": saved_count,
        "feedback_count": feedback_count,
        "latest_signal_count": latest_signal_count,
        "fallback_signal_count": fallback_signal_count,
        "negative_feedback_count": negative_feedback_count,
        "positive_feedback_count": positive_feedback_count,
        "recommendations": _build_recommendations(
            status=status,
            saved_count=saved_count,
            fallback_signal_count=fallback_signal_count,
            negative_feedback_count=negative_feedback_count,
        ),
    }
