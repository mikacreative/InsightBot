from __future__ import annotations

import re

import streamlit as st

from insightbot.config import load_tasks_config
from insightbot.signal_desk.compiler import compile_room_to_task
from insightbot.signal_desk.models import BriefingRoom
from insightbot.signal_desk.presets import get_use_case_template, list_judgement_lenses
from insightbot.signal_desk.source_packs import list_source_packs
from insightbot.signal_desk.storage import load_rooms, save_room

from .room_detail import render_room_detail


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "client_opportunity_radar"


def _parse_focus_areas(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]


def render_rooms_tab(bot_dir: str, channels_data: dict, save_task_definition) -> None:
    st.subheader("Signal Desk")
    st.caption("Create briefing rooms that compile into runnable InsightBot tasks.")

    rooms = load_rooms(bot_dir=bot_dir)
    if rooms:
        room_options = list(rooms.keys())
        selected_room_id = st.selectbox(
            "Briefing rooms",
            options=room_options,
            format_func=lambda room_id: f"{rooms[room_id].name} ({room_id})",
        )
        render_room_detail(
            rooms[selected_room_id],
            bot_dir=bot_dir,
            load_task_config=lambda task_id: load_tasks_config(task_id, bot_dir),
        )
    else:
        st.info("No briefing rooms yet. Create a Client Opportunity Radar below.")

    st.divider()
    st.markdown("### Create Client Opportunity Radar")

    template = get_use_case_template("client_opportunity_radar")
    source_packs = list_source_packs()
    judgement_lenses = list_judgement_lenses()
    channel_options = list((channels_data or {}).get("channels", {}).keys())

    source_pack_ids = [pack["id"] for pack in source_packs]
    default_pack_ids = [
        pack_id for pack_id in template.get("recommended_source_pack_ids", []) if pack_id in source_pack_ids
    ]
    lens_ids = [lens["id"] for lens in judgement_lenses]
    default_lens_ids = [
        lens_id for lens_id in template.get("default_judgement_lens_ids", []) if lens_id in lens_ids
    ]
    default_schedule = template.get("default_schedule", {"hour": 8, "minute": 0})

    with st.form("create_signal_desk_room"):
        name = st.text_input("Room name", value="Client Opportunity Radar").strip()
        room_id = st.text_input("Room ID", value=_slugify(name)).strip()
        topic = st.text_area(
            "Topic",
            value="Client-relevant marketing communications signals, campaign cases, and pitchable ideas.",
            height=90,
        ).strip()
        focus_areas_text = st.text_area(
            "Focus areas",
            placeholder="One per line, for example:\nbeauty retail\nAI marketing\nsocial commerce",
            height=90,
        )
        audience = st.text_input("Audience", value="senior account and strategy team").strip()

        selected_source_pack_ids = st.multiselect(
            "Source packs",
            options=source_pack_ids,
            default=default_pack_ids,
            format_func=lambda pack_id: next(
                (pack["name"] for pack in source_packs if pack["id"] == pack_id),
                pack_id,
            ),
        )
        selected_lens_ids = st.multiselect(
            "Judgement lenses",
            options=lens_ids,
            default=default_lens_ids,
            format_func=lambda lens_id: next(
                (lens["label"] for lens in judgement_lenses if lens["id"] == lens_id),
                lens_id,
            ),
        )
        selected_channels = st.multiselect("Channels", options=channel_options, default=[])

        sched_col1, sched_col2, sched_col3 = st.columns([1, 1, 1.2])
        with sched_col1:
            hour = st.number_input(
                "Hour",
                min_value=0,
                max_value=23,
                value=int(default_schedule.get("hour", 8)),
            )
        with sched_col2:
            minute = st.number_input(
                "Minute",
                min_value=0,
                max_value=59,
                value=int(default_schedule.get("minute", 0)),
            )
        with sched_col3:
            enabled = st.checkbox("Enable compiled task", value=False)

        submitted = st.form_submit_button("Create room and task", use_container_width=True)

    if not submitted:
        return

    if not room_id:
        st.error("Room ID is required.")
        return
    if room_id in rooms:
        st.error("Room ID already exists.")
        return
    if not name or not topic:
        st.error("Room name and topic are required.")
        return
    if not selected_source_pack_ids:
        st.error("Select at least one source pack.")
        return
    if not selected_lens_ids:
        st.error("Select at least one judgement lens.")
        return

    room = BriefingRoom(
        id=room_id,
        name=name,
        topic=topic,
        source_pack_ids=selected_source_pack_ids,
        editorial_preset_id=template["default_editorial_preset_id"],
        judgement_lens_ids=selected_lens_ids,
        channels=selected_channels,
        schedule={"hour": int(hour), "minute": int(minute)},
        enabled=enabled,
        use_case_template_id=template["id"],
        audience=audience or "senior account and strategy team",
        focus_areas=_parse_focus_areas(focus_areas_text),
    )
    save_room(room, bot_dir=bot_dir)
    task_id, task_def = compile_room_to_task(room)
    save_task_definition(task_id, task_def)
    st.success(f"Created briefing room `{room.id}` and compiled task `{task_id}`.")
    st.rerun()
