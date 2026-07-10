from __future__ import annotations

import streamlit as st

from insightbot.signal_desk.feedback import list_feedback, list_saved_signals
from insightbot.signal_desk.health import build_pattern_health_summary
from insightbot.signal_desk.storage import load_rooms


STATUS_LABELS = {
    "healthy": "Healthy",
    "needs_attention": "Needs attention",
    "no_data": "No data",
}


def build_signal_workspace_rows(
    rooms: dict,
    saved_signals: list[dict],
    feedback_records: list[dict],
) -> list[dict]:
    rows = []
    for room_id, room in rooms.items():
        summary = build_pattern_health_summary(
            room,
            saved_signals=saved_signals,
            feedback_records=feedback_records,
        )
        rows.append(
            {
                "room_id": room_id,
                "room_name": room.name,
                "pattern_id": room.use_case_template_id,
                "status": summary["status"],
                "saved_count": summary["saved_count"],
                "feedback_count": summary["feedback_count"],
                "recommendations": list(summary["recommendations"]),
            }
        )
    return rows


def render_signals_tab(bot_dir: str) -> None:
    st.subheader("Signals")
    st.caption("Review room-level signal readiness before turning signals into saved assets or briefs.")

    rooms = load_rooms(bot_dir=bot_dir)
    if not rooms:
        st.info("Create a room first. Signals will appear after room refreshes and saved reviews.")
        return

    saved_signals = list_saved_signals(bot_dir=bot_dir)
    feedback_records = list_feedback(bot_dir=bot_dir)
    rows = build_signal_workspace_rows(rooms, saved_signals, feedback_records)

    total_saved = sum(row["saved_count"] for row in rows)
    total_feedback = sum(row["feedback_count"] for row in rows)
    needs_attention = sum(1 for row in rows if row["status"] == "needs_attention")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Rooms", len(rows))
    metric_cols[1].metric("Saved signals", total_saved)
    metric_cols[2].metric("Needs attention", needs_attention)
    st.caption(f"Feedback events: {total_feedback}")

    for row in rows:
        with st.container(border=True):
            st.markdown(f"**{row['room_name']}**")
            st.caption(
                f"Room: `{row['room_id']}` | Pattern: `{row['pattern_id']}` | "
                f"Status: {STATUS_LABELS.get(row['status'], row['status'])}"
            )
            st.markdown(
                f"Saved signals: **{row['saved_count']}** | "
                f"Feedback events: **{row['feedback_count']}**"
            )
            for recommendation in row["recommendations"]:
                st.markdown(f"- {recommendation}")
