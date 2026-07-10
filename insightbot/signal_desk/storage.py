from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from insightbot.paths import signal_desk_rooms_file_path
from insightbot.signal_desk.models import BriefingRoom

_LOCK_RETRY_DELAY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 5.0


def _atomic_write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{target}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
    os.replace(tmp, target)


@contextmanager
def _room_storage_lock(path: str):
    lock_path = path + ".lock"
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    fd = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for room storage lock: {lock_path}")
            time.sleep(_LOCK_RETRY_DELAY_SECONDS)

    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass


def load_rooms(bot_dir: str | None = None) -> dict[str, BriefingRoom]:
    path = signal_desk_rooms_file_path(bot_dir)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rooms = payload.get("rooms", {})
    if not isinstance(rooms, dict):
        raise ValueError("Rooms payload must be an object")
    loaded_rooms = {}
    for room_id, room_data in rooms.items():
        if not isinstance(room_data, dict):
            raise ValueError(f"Room entry must be an object: {room_id}")
        loaded_rooms[room_id] = BriefingRoom.from_dict(room_data)
    return loaded_rooms


def _save_rooms_unlocked(rooms: dict[str, BriefingRoom], bot_dir: str | None = None) -> None:
    payload = {"rooms": {room_id: room.to_dict() for room_id, room in rooms.items()}}
    _atomic_write_json(signal_desk_rooms_file_path(bot_dir), payload)


def save_rooms(rooms: dict[str, BriefingRoom], bot_dir: str | None = None) -> None:
    path = signal_desk_rooms_file_path(bot_dir)
    with _room_storage_lock(path):
        _save_rooms_unlocked(rooms, bot_dir=bot_dir)


def save_room(room: BriefingRoom, bot_dir: str | None = None) -> None:
    path = signal_desk_rooms_file_path(bot_dir)
    with _room_storage_lock(path):
        rooms = load_rooms(bot_dir=bot_dir)
        rooms[room.id] = room
        _save_rooms_unlocked(rooms, bot_dir=bot_dir)


def delete_room(room_id: str, bot_dir: str | None = None) -> None:
    path = signal_desk_rooms_file_path(bot_dir)
    with _room_storage_lock(path):
        rooms = load_rooms(bot_dir=bot_dir)
        rooms.pop(room_id, None)
        _save_rooms_unlocked(rooms, bot_dir=bot_dir)
