from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from insightbot.paths import signal_desk_feedback_file_path, signal_desk_saved_signals_file_path
from insightbot.signal_desk.models import FeedbackRecord, SavedSignal, SignalItem

ALLOWED_FEEDBACK_ACTIONS = {
    "useful",
    "not_relevant",
    "too_shallow",
    "good_for_pitch",
    "good_for_client",
    "already_known",
    "need_more_like_this",
}

_LOCK_RETRY_DELAY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 5.0


@contextmanager
def _jsonl_append_lock(path: str):
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
                raise TimeoutError(f"Timed out waiting for JSONL append lock: {lock_path}")
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


def _append_jsonl(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _jsonl_append_lock(path):
        with target.open("a", encoding="utf-8") as f:
            f.write(line)


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []

    items: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def save_signal(
    signal: SignalItem,
    tags: list[str] | None = None,
    notes: str = "",
    bot_dir: str | None = None,
) -> SavedSignal:
    saved = SavedSignal(
        id=f"saved_{uuid.uuid4().hex[:12]}",
        signal=signal.to_dict(),
        room_id=signal.room_id,
        tags=list(tags if tags is not None else signal.save_tags),
        notes=notes,
    )
    _append_jsonl(signal_desk_saved_signals_file_path(bot_dir), saved.to_dict())
    return saved


def list_saved_signals(room_id: str | None = None, bot_dir: str | None = None) -> list[dict[str, Any]]:
    items = _read_jsonl(signal_desk_saved_signals_file_path(bot_dir))
    if room_id is None:
        return items
    return [item for item in items if item.get("room_id") == room_id]


def append_feedback(
    signal_id: str,
    room_id: str,
    action: str,
    note: str = "",
    pattern_id: str = "",
    context: dict[str, Any] | None = None,
    bot_dir: str | None = None,
) -> FeedbackRecord:
    if action not in ALLOWED_FEEDBACK_ACTIONS:
        raise ValueError(f"Unsupported feedback action: {action}")

    record = FeedbackRecord(
        id=f"fb_{uuid.uuid4().hex[:12]}",
        signal_id=signal_id,
        room_id=room_id,
        action=action,
        note=note,
        pattern_id=pattern_id,
        context=dict(context or {}),
    )
    _append_jsonl(signal_desk_feedback_file_path(bot_dir), record.to_dict())
    return record


def list_feedback(room_id: str | None = None, bot_dir: str | None = None) -> list[dict[str, Any]]:
    items = _read_jsonl(signal_desk_feedback_file_path(bot_dir))
    if room_id is None:
        return items
    return [item for item in items if item.get("room_id") == room_id]


def summarize_feedback(room_id: str, bot_dir: str | None = None) -> dict[str, int]:
    counts = Counter(item.get("action") for item in list_feedback(room_id=room_id, bot_dir=bot_dir))
    return {key: count for key, count in counts.items() if isinstance(key, str)}
