from __future__ import annotations

from copy import deepcopy
from typing import Any

from insightbot.signal_desk.models import BriefingRoom
from insightbot.signal_desk.presets import get_editorial_preset, get_judgement_lenses
from insightbot.signal_desk.source_packs import get_source_pack, merge_source_packs


def _build_selection_rules(room: BriefingRoom, preset: dict[str, Any], lenses: list[dict[str, Any]]) -> list[str]:
    rules = list(preset.get("selection_rules", []))
    rules.append(f"Room topic: {room.topic}")
    if room.focus_areas:
        rules.append(f"Room focus areas: {', '.join(room.focus_areas)}")
    for lens in lenses:
        rules.append(f"{lens['label']}: {lens['core_question']}")
    return rules


def _build_pipeline_config(room: BriefingRoom) -> dict[str, Any]:
    preset = get_editorial_preset(room.editorial_preset_id)
    lenses = get_judgement_lenses(room.judgement_lens_ids)
    pipeline_config = deepcopy(preset)
    pipeline_config["selection_rules"] = _build_selection_rules(room, preset, lenses)
    pipeline_config["judgement_lenses"] = lenses
    pipeline_config["room_topic"] = room.topic
    pipeline_config["room_focus_areas"] = list(room.focus_areas)
    return pipeline_config


def compile_room_to_task(room: BriefingRoom) -> tuple[str, dict[str, Any]]:
    source_packs = [get_source_pack(pack_id) for pack_id in room.source_pack_ids]
    merged_sources = merge_source_packs(source_packs)
    task_id = room.compiled_task_id or f"room_{room.id}"

    task_def: dict[str, Any] = {
        "name": room.name,
        "enabled": room.enabled,
        "feeds": merged_sources["feeds"],
        "pipeline": "editorial",
        "_editorial_pipeline_mode": "editorial-intelligence",
        "_signal_desk_room_id": room.id,
        "_signal_desk_compiled": True,
        "pipeline_config": _build_pipeline_config(room),
        "search": merged_sources["search"],
        "channels": list(room.channels),
        "schedule": dict(room.schedule),
    }
    return task_id, task_def
