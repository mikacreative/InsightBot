from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from insightbot.signal_desk.feedback import (
    append_feedback,
    list_feedback,
    list_saved_signals,
    save_signal,
    summarize_feedback,
)
from insightbot.signal_desk.health import build_pattern_health_summary
from insightbot.signal_desk.models import BriefingRoom, SignalItem
from insightbot.signal_desk.signals import signal_items_from_run_result, summarize_signal_output_quality
from insightbot.task_runner import run_task

FEEDBACK_ACTION_LABELS = {
    "useful": "Useful",
    "not_relevant": "Not relevant",
    "too_shallow": "Too shallow",
    "good_for_pitch": "Good for pitch",
    "good_for_client": "Good for client",
}


def _is_markdown_fallback_signal(signal: SignalItem) -> bool:
    return (
        signal.confidence.lower() == "low"
        and ("fallback" in signal.save_tags or "manual_review" in signal.judgement_lens)
    )


def _format_feedback_summary(summary: dict[str, int]) -> str:
    if not summary:
        return "No feedback yet."

    ordered_parts = [
        f"{label}: {summary[action]}"
        for action, label in FEEDBACK_ACTION_LABELS.items()
        if summary.get(action)
    ]
    ordered_parts.extend(
        f"{action}: {count}"
        for action, count in sorted(summary.items())
        if action not in FEEDBACK_ACTION_LABELS
    )
    return " | ".join(ordered_parts)


def _render_feedback_summary(room_id: str, bot_dir: str) -> None:
    summary = summarize_feedback(room_id, bot_dir=bot_dir)
    st.caption("Room feedback: " + _format_feedback_summary(summary))


def _feedback_context_for_room(room: BriefingRoom) -> dict:
    intent = room.client_context.get("intent")
    if isinstance(intent, dict):
        return intent
    return dict(room.client_context)


def _render_signal_card(signal: SignalItem, room: BriefingRoom, bot_dir: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{signal.what_happened or 'Untitled signal'}**")
        st.caption(f"Confidence: {signal.confidence} | Lens: {', '.join(signal.judgement_lens) or 'n/a'}")
        if signal.why_it_matters:
            st.markdown(f"**Why it matters**: {signal.why_it_matters}")
        if signal.client_relevance:
            st.markdown(f"**Client relevance**: {signal.client_relevance}")
        if signal.suggested_action:
            st.markdown(f"**Suggested action**: {signal.suggested_action}")
        if signal.source.get("url"):
            st.markdown(f"[Source]({signal.source['url']})")

        if st.button("Save signal", key=f"save_signal::{signal.room_id}::{signal.id}"):
            saved = save_signal(signal, bot_dir=bot_dir)
            st.success(f"Saved as {saved.id}")

        st.caption("Feedback")
        feedback_cols = st.columns(len(FEEDBACK_ACTION_LABELS))
        for col, (action, label) in zip(feedback_cols, FEEDBACK_ACTION_LABELS.items(), strict=True):
            if col.button(label, key=f"signal_feedback::{signal.room_id}::{signal.id}::{action}"):
                append_feedback(
                    signal_id=signal.id,
                    room_id=signal.room_id,
                    action=action,
                    pattern_id=room.use_case_template_id,
                    context=_feedback_context_for_room(room),
                    bot_dir=bot_dir,
                )
                st.success(f"Feedback recorded: {label}")


def render_room_detail(room: BriefingRoom, bot_dir: str, load_task_config) -> None:
    st.markdown(f"### {room.name}")
    st.caption(f"Room ID: `{room.id}` | Compiled task: `{room.compiled_task_id}`")

    meta_col1, meta_col2, meta_col3 = st.columns(3)
    meta_col1.metric("Source packs", len(room.source_pack_ids))
    meta_col2.metric("Judgement lenses", len(room.judgement_lens_ids))
    meta_col3.metric("Channels", len(room.channels))

    st.markdown(f"**Topic**: {room.topic}")
    if room.focus_areas:
        st.markdown("**Focus areas**: " + ", ".join(room.focus_areas))
    feedback_summary_slot = st.empty()
    with feedback_summary_slot:
        _render_feedback_summary(room.id, bot_dir)

    result_key = f"signal_desk_dry_run::{room.id}"
    if st.button("Refresh selected signals", type="primary", key=f"signal_desk_run::{room.id}"):
        with st.spinner(f"Refreshing selected signals for {room.name}..."):
            try:
                result = run_task(
                    room.compiled_task_id,
                    config_loader_fn=lambda: load_task_config(room.compiled_task_id),
                    dry_run=True,
                )
            except Exception as exc:
                result = {
                    "ok": False,
                    "task_id": room.compiled_task_id,
                    "pipeline": "",
                    "dry_run": True,
                    "final_markdown": "",
                    "channel_results": [],
                    "stage_results": {},
                    "error": (
                        f"Compiled task `{room.compiled_task_id}` could not be loaded or run: {exc}. "
                        "Recompile or recreate this briefing room."
                    ),
                }
        result["_signal_desk_run_id"] = datetime.now(UTC).strftime("dry_run_%Y%m%d%H%M%S")
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not result:
        st.info("Refresh selected signals to turn the latest room output into signal cards.")
        return

    if result.get("ok"):
        st.success("Dry run completed.")
    else:
        st.error(f"Dry run failed: {result.get('error') or 'Unknown error'}")

    signals = signal_items_from_run_result(
        room_id=room.id,
        run_id=result.get("_signal_desk_run_id") or result.get("task_id") or room.compiled_task_id,
        run_result=result,
    )
    output_quality = summarize_signal_output_quality(signals)
    st.caption(
        f"Output quality: {output_quality['status']} | "
        f"Structured: {output_quality['structured_count']} | "
        f"Fallback: {output_quality['fallback_count']} | "
        f"Missing source: {output_quality['missing_source_count']}"
    )
    st.markdown("#### Signal cards")
    if not signals:
        st.warning("No signal cards could be extracted from this run result.")
    elif all(_is_markdown_fallback_signal(signal) for signal in signals):
        st.warning(
            "Structured shortlist was not available in this run result. "
            "These low-confidence cards were extracted from final markdown and need manual review."
        )
    for signal in signals:
        _render_signal_card(signal, room, bot_dir)
    with feedback_summary_slot:
        _render_feedback_summary(room.id, bot_dir)

    health_summary = build_pattern_health_summary(
        room,
        saved_signals=list_saved_signals(room_id=room.id, bot_dir=bot_dir),
        feedback_records=list_feedback(room_id=room.id, bot_dir=bot_dir),
        latest_signals=signals,
    )
    with st.expander("Pattern health", expanded=health_summary["status"] == "needs_attention"):
        st.caption(f"Status: {health_summary['status']}")
        st.markdown(
            f"Latest signals: **{health_summary['latest_signal_count']}** | "
            f"Fallback/manual review signals: **{health_summary['fallback_signal_count']}**"
        )
        for recommendation in health_summary["recommendations"]:
            st.markdown(f"- {recommendation}")
        if output_quality["recommendations"]:
            st.markdown("**Output quality recommendations**")
            for recommendation in output_quality["recommendations"]:
                st.markdown(f"- {recommendation}")

    with st.expander("Final markdown", expanded=False):
        st.markdown(result.get("final_markdown") or "No final markdown.")
    with st.expander("Raw dry run result", expanded=False):
        st.json(result, expanded=False)
