from __future__ import annotations

import json
import os
from pathlib import Path

from insightbot.paths import signal_desk_rooms_file_path
from insightbot.signal_desk.models import BriefingRoom


def _atomic_write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
    os.replace(tmp, target)


def load_rooms(bot_dir: str | None = None) -> dict[str, BriefingRoom]:
    path = signal_desk_rooms_file_path(bot_dir)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rooms = payload.get("rooms", {})
    return {
        room_id: BriefingRoom.from_dict(room_data)
        for room_id, room_data in rooms.items()
        if isinstance(room_data, dict)
    }


def save_rooms(rooms: dict[str, BriefingRoom], bot_dir: str | None = None) -> None:
    payload = {"rooms": {room_id: room.to_dict() for room_id, room in rooms.items()}}
    _atomic_write_json(signal_desk_rooms_file_path(bot_dir), payload)


def save_room(room: BriefingRoom, bot_dir: str | None = None) -> None:
    rooms = load_rooms(bot_dir=bot_dir)
    rooms[room.id] = room
    save_rooms(rooms, bot_dir=bot_dir)


def delete_room(room_id: str, bot_dir: str | None = None) -> None:
    rooms = load_rooms(bot_dir=bot_dir)
    rooms.pop(room_id, None)
    save_rooms(rooms, bot_dir=bot_dir)
