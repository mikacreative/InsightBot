from __future__ import annotations

import streamlit as st

from insightbot.signal_desk.feedback import list_saved_signals


def render_saved_signals_tab(bot_dir: str) -> None:
    st.subheader("Saved Signals")
    st.caption("Signals saved from Signal Desk dry runs.")

    saved_signals = list_saved_signals(bot_dir=bot_dir)
    if not saved_signals:
        st.info("No saved signals yet.")
        return

    room_ids = sorted({str(item.get("room_id", "")) for item in saved_signals if item.get("room_id")})
    selected_room = st.selectbox("Filter by room", options=["All"] + room_ids)
    visible_signals = [
        item for item in saved_signals
        if selected_room == "All" or item.get("room_id") == selected_room
    ]

    st.caption(f"Showing {len(visible_signals)} of {len(saved_signals)} saved signals.")
    for item in reversed(visible_signals):
        signal = item.get("signal", {}) if isinstance(item.get("signal"), dict) else {}
        with st.container(border=True):
            st.markdown(f"**{signal.get('what_happened') or item.get('id', 'Untitled signal')}**")
            st.caption(
                f"Saved: {item.get('created_at', '')} | Room: {item.get('room_id', '')} | "
                f"Confidence: {signal.get('confidence', 'n/a')}"
            )
            if signal.get("why_it_matters"):
                st.markdown(f"**Why it matters**: {signal['why_it_matters']}")
            if signal.get("client_relevance"):
                st.markdown(f"**Client relevance**: {signal['client_relevance']}")
            if signal.get("suggested_action"):
                st.markdown(f"**Suggested action**: {signal['suggested_action']}")
            tags = item.get("tags") or []
            if tags:
                st.caption("Tags: " + ", ".join(str(tag) for tag in tags))
            source = signal.get("source", {}) if isinstance(signal.get("source"), dict) else {}
            if source.get("url"):
                st.markdown(f"[Source]({source['url']})")
