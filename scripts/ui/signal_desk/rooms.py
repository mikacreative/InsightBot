from __future__ import annotations

import re

import streamlit as st

from insightbot.config import load_tasks, load_tasks_config
from insightbot.signal_desk.compiler import compile_room_to_task
from insightbot.signal_desk.models import BriefingRoom
from insightbot.signal_desk.patterns import IntentContract, list_pattern_contracts
from insightbot.signal_desk.presets import get_editorial_preset, get_use_case_template, list_judgement_lenses
from insightbot.signal_desk.source_packs import list_source_packs
from insightbot.signal_desk.storage import load_rooms, save_room

from .room_detail import render_room_detail


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "client_opportunity_radar"


def _parse_focus_areas(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]


def _build_signal_desk_inspector(
    template: dict,
    source_packs: list[dict],
    judgement_lenses: list[dict],
) -> dict:
    recommended_pack_ids = set(template.get("recommended_source_pack_ids", []))
    default_lens_ids = set(template.get("default_judgement_lens_ids", []))
    preset = get_editorial_preset(template["default_editorial_preset_id"])
    return {
        "source_packs": [
            {
                "id": pack["id"],
                "name": pack["name"],
                "coverage": pack.get("coverage", ""),
                "limitations": pack.get("limitations", ""),
                "bias": list(pack.get("bias", [])),
                "freshness": pack.get("freshness", ""),
                "recommended": pack["id"] in recommended_pack_ids,
            }
            for pack in source_packs
        ],
        "editorial_preset": {
            "id": preset["id"],
            "name": preset["name"],
            "shortlist_size": preset.get("shortlist_size"),
            "selection_rules": list(preset.get("selection_rules", [])),
            "quality_checks": list(preset.get("quality_checks", [])),
        },
        "judgement_lenses": [
            {
                "id": lens["id"],
                "label": lens["label"],
                "core_question": lens.get("core_question", ""),
                "default": lens["id"] in default_lens_ids,
            }
            for lens in judgement_lenses
        ],
    }


def _render_signal_desk_inspector(inspector: dict) -> None:
    with st.expander("Source, preset, and lens inspector", expanded=False):
        st.markdown("**Source packs**")
        for pack in inspector["source_packs"]:
            suffix = " · recommended" if pack["recommended"] else ""
            st.markdown(f"**{pack['name']}** (`{pack['id']}`){suffix}")
            st.caption(
                f"Coverage: {pack['coverage']} | Limitations: {pack['limitations']} | "
                f"Bias: {', '.join(pack['bias']) or 'n/a'} | Freshness: {pack['freshness'] or 'n/a'}"
            )

        preset = inspector["editorial_preset"]
        st.markdown(f"**Editorial preset: {preset['name']}** (`{preset['id']}`)")
        st.caption(f"Shortlist size: {preset['shortlist_size']}")
        st.markdown("Selection rules: " + "; ".join(preset["selection_rules"]))
        st.markdown("Quality checks: " + "; ".join(preset["quality_checks"]))

        st.markdown("**Judgement lenses**")
        for lens in inspector["judgement_lenses"]:
            suffix = " · default" if lens["default"] else ""
            st.markdown(f"**{lens['label']}** (`{lens['id']}`){suffix}")
            st.caption(lens["core_question"])


def render_rooms_tab(bot_dir: str, channels_data: dict, save_task_definition) -> None:
    st.subheader("Signal Desk")
    st.caption("Create intelligence rooms by choosing a pattern and adding work context.")

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
    st.markdown("### New intelligence room")

    template = get_use_case_template("client_opportunity_radar")
    patterns = list_pattern_contracts()
    source_packs = list_source_packs()
    judgement_lenses = list_judgement_lenses()
    channel_options = list((channels_data or {}).get("channels", {}).keys())

    pattern_options = [pattern.id for pattern in patterns]
    selected_pattern_id = st.selectbox(
        "Pattern",
        options=pattern_options,
        format_func=lambda pattern_id: next(
            (pattern.name for pattern in patterns if pattern.id == pattern_id),
            pattern_id,
        ),
    )
    selected_pattern = next(pattern for pattern in patterns if pattern.id == selected_pattern_id)

    source_pack_ids = [pack["id"] for pack in source_packs]
    default_pack_ids = [
        pack_id for pack_id in selected_pattern.default_source_pack_ids if pack_id in source_pack_ids
    ]
    lens_ids = [lens["id"] for lens in judgement_lenses]
    default_lens_ids = [
        lens_id for lens_id in selected_pattern.default_judgement_lens_ids if lens_id in lens_ids
    ]
    default_schedule = template.get("default_schedule", {"hour": 8, "minute": 0})
    _render_signal_desk_inspector(
        _build_signal_desk_inspector(
            template=template,
            source_packs=source_packs,
            judgement_lenses=judgement_lenses,
        )
    )

    with st.form("create_signal_desk_room"):
        client = st.text_input("Client", placeholder="Sephora, IKEA, or a client group").strip()
        category = st.text_input("Category", placeholder="beauty retail, home, automotive").strip()
        focus_topics_text = st.text_area(
            "Focus topics",
            placeholder="One per line, for example:\nAI retail\nsocial commerce\ncampaign cases",
            height=90,
        )
        output_intent = st.selectbox(
            "Output intent",
            options=[
                "client_conversation",
                "proposal_angle",
                "internal_inspiration",
                "trend_observation",
            ],
        )
        time_window = st.selectbox(
            "Time window",
            options=["last_7_days", "last_14_days", "last_30_days"],
        )
        name = st.text_input("Room name", value=selected_pattern.name).strip()
        room_id = st.text_input("Room ID", value=_slugify(name)).strip()
        topic = st.text_area(
            "Topic",
            value=selected_pattern.user_job,
            height=90,
        ).strip()
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

        submitted = st.form_submit_button("Create room", use_container_width=True)

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
    if not client or not category:
        st.error("Client and category are required.")
        return
    if not selected_source_pack_ids:
        st.error("Select at least one source pack.")
        return
    if not selected_lens_ids:
        st.error("Select at least one judgement lens.")
        return

    focus_topics = _parse_focus_areas(focus_topics_text)
    if not focus_topics:
        st.error("Add at least one focus topic.")
        return

    intent = IntentContract(
        pattern_id=selected_pattern.id,
        room_id=room_id,
        client=client,
        category=category,
        focus_topics=focus_topics,
        output_intent=output_intent,
        time_window=time_window,
    )

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
        use_case_template_id=selected_pattern.id,
        audience=audience or "senior account and strategy team",
        focus_areas=focus_topics,
        client_context={"intent": intent.to_dict()},
    )
    task_id, task_def = compile_room_to_task(room)
    existing_tasks = load_tasks(bot_dir).get("tasks", {})
    if task_id in existing_tasks:
        st.error(
            f"Compiled task ID `{task_id}` already exists. "
            "Choose a different Room ID before creating this briefing room."
        )
        return

    save_room(room, bot_dir=bot_dir)
    save_task_definition(task_id, task_def)
    st.success(f"Created briefing room `{room.id}` and compiled task `{task_id}`.")
    st.rerun()
