from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from insightbot.signal_desk.feedback import save_signal
from insightbot.signal_desk.models import BriefingRoom, SignalItem
from insightbot.signal_desk.signals import signal_items_from_run_result
from insightbot.task_runner import run_task


def _is_markdown_fallback_signal(signal: SignalItem) -> bool:
    return (
        signal.confidence.lower() == "low"
        and ("fallback" in signal.save_tags or "manual_review" in signal.judgement_lens)
    )


def _render_signal_card(signal: SignalItem, bot_dir: str) -> None:
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

    result_key = f"signal_desk_dry_run::{room.id}"
    if st.button("Dry run room", type="primary", key=f"signal_desk_run::{room.id}"):
        with st.spinner(f"Running dry run for {room.name}..."):
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
        st.info("Run a dry run to turn the latest output into signal cards.")
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
    st.markdown("#### Signal cards")
    if not signals:
        st.warning("No signal cards could be extracted from this run result.")
    elif all(_is_markdown_fallback_signal(signal) for signal in signals):
        st.warning(
            "Structured shortlist was not available in this run result. "
            "These low-confidence cards were extracted from final markdown and need manual review."
        )
    for signal in signals:
        _render_signal_card(signal, bot_dir)

    with st.expander("Final markdown", expanded=False):
        st.markdown(result.get("final_markdown") or "No final markdown.")
    with st.expander("Raw dry run result", expanded=False):
        st.json(result, expanded=False)
