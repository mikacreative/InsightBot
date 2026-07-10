from __future__ import annotations

import streamlit as st

from insightbot.signal_desk.briefs import create_brief_from_saved_signals, list_briefs
from insightbot.signal_desk.feedback import list_saved_signals
from insightbot.signal_desk.storage import load_rooms


def build_brief_room_options(rooms: dict, saved_signals: list[dict]) -> list[str]:
    room_ids_with_saved = {str(item.get("room_id", "")) for item in saved_signals}
    return [room_id for room_id in rooms if room_id in room_ids_with_saved]


def build_brief_intent_options() -> list[tuple[str, str]]:
    return [
        ("client_conversation", "Client conversation brief"),
        ("proposal_angle", "Proposal angle brief"),
        ("internal_inspiration", "Internal inspiration brief"),
        ("trend_observation", "Trend observation brief"),
    ]


def render_briefs_tab(bot_dir: str) -> None:
    st.subheader("Briefs")
    st.caption("Turn saved signals into a lightweight client conversation or proposal brief.")

    rooms = load_rooms(bot_dir=bot_dir)
    saved_signals = list_saved_signals(bot_dir=bot_dir)
    briefs = list_briefs(bot_dir=bot_dir)

    if not rooms:
        st.info("Create a room before generating briefs.")
        return

    room_options = build_brief_room_options(rooms, saved_signals)
    if room_options:
        selected_room_id = st.selectbox(
            "Room",
            options=room_options,
            format_func=lambda room_id: f"{rooms[room_id].name} ({room_id})",
        )
        intent_options = build_brief_intent_options()
        output_intent = st.selectbox(
            "Brief type",
            options=[item[0] for item in intent_options],
            format_func=dict(intent_options).get,
        )
        if st.button("Generate brief from saved signals", type="primary"):
            try:
                artifact = create_brief_from_saved_signals(
                    rooms[selected_room_id],
                    saved_signals,
                    output_intent=output_intent,
                    bot_dir=bot_dir,
                )
            except ValueError as exc:
                st.warning(str(exc))
            else:
                st.success(f"Generated brief `{artifact.id}`.")
                st.rerun()
    else:
        st.info("Save at least one signal in a room before generating a brief.")

    st.divider()
    st.markdown("### Generated briefs")
    if not briefs:
        st.info("No briefs generated yet.")
        return

    room_filter_options = ["All"] + sorted({str(item.get("room_id", "")) for item in briefs if item.get("room_id")})
    selected_filter = st.selectbox("Filter briefs by room", options=room_filter_options)
    visible_briefs = [
        item for item in briefs
        if selected_filter == "All" or item.get("room_id") == selected_filter
    ]
    intent_labels = dict(build_brief_intent_options())
    for item in reversed(visible_briefs):
        with st.container(border=True):
            st.markdown(f"**{item.get('title') or item.get('id', 'Untitled brief')}**")
            st.caption(
                f"Brief: `{item.get('id', '')}` | Room: `{item.get('room_id', '')}` | "
                f"Type: {intent_labels.get(item.get('output_intent', ''), item.get('output_intent', ''))} | "
                f"Created: {item.get('created_at', '')}"
            )
            source_signal_ids = item.get("source_signal_ids") or []
            st.caption(f"Source signals: {len(source_signal_ids)}")
            with st.expander("Brief markdown", expanded=False):
                st.markdown(item.get("markdown") or "No markdown.")
