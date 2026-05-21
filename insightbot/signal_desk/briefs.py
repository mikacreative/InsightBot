from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from insightbot.paths import signal_desk_briefs_file_path
from insightbot.signal_desk.models import BriefArtifact, BriefingRoom

_LOCK_RETRY_DELAY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 5.0

BRIEF_INTENT_LABELS = {
    "client_conversation": "Client Conversation Brief",
    "proposal_angle": "Proposal Angle Brief",
    "internal_inspiration": "Internal Inspiration Brief",
    "trend_observation": "Trend Observation Brief",
}

BRIEF_INTENT_SECTIONS = {
    "client_conversation": [
        "Executive takeaways",
        "Client conversation starters",
        "Recommended next actions",
        "Source signals",
    ],
    "proposal_angle": [
        "Executive takeaways",
        "Pitch angles",
        "Proof points",
        "Recommended next actions",
        "Source signals",
    ],
    "internal_inspiration": [
        "Executive takeaways",
        "Inspiration hooks",
        "Reusable references",
        "Source signals",
    ],
    "trend_observation": [
        "Executive takeaways",
        "Trend observations",
        "Implications",
        "Source signals",
    ],
}


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


def create_brief_from_saved_signals(
    room: BriefingRoom,
    saved_signals: list[dict],
    output_intent: str = "client_conversation",
    bot_dir: str | None = None,
) -> BriefArtifact:
    room_signals = [item for item in saved_signals if item.get("room_id") == room.id]
    if not room_signals:
        raise ValueError(f"No saved signals for room: {room.id}")

    title = room.name
    artifact = BriefArtifact(
        id=f"brief_{uuid.uuid4().hex[:12]}",
        room_id=room.id,
        title=f"{title} Brief",
        output_intent=output_intent,
        source_signal_ids=[str(item.get("id", "")) for item in room_signals],
        markdown=_render_brief_markdown(title, room_signals, output_intent),
    )
    _append_jsonl(signal_desk_briefs_file_path(bot_dir), artifact.to_dict())
    return artifact


def list_briefs(room_id: str | None = None, bot_dir: str | None = None) -> list[dict[str, Any]]:
    items = _read_jsonl(signal_desk_briefs_file_path(bot_dir))
    if room_id is None:
        return items
    return [item for item in items if item.get("room_id") == room_id]


def _signal_payload(item: dict) -> dict:
    signal = item.get("signal", {})
    return signal if isinstance(signal, dict) else {}


def _render_brief_markdown(title: str, saved_signals: list[dict], output_intent: str) -> str:
    intent_label = BRIEF_INTENT_LABELS.get(output_intent, "Signal Desk Brief")
    sections = BRIEF_INTENT_SECTIONS.get(output_intent, BRIEF_INTENT_SECTIONS["client_conversation"])
    heading = f"{title} - {intent_label}"
    signals = [_signal_payload(item) for item in saved_signals]

    lines = [
        f"# {heading}",
        "",
        f"Source signals: {len(signals)}",
        "",
        f"## {sections[0]}",
    ]
    for signal in signals:
        lines.append(f"- {signal.get('what_happened', '')}: {signal.get('why_it_matters', '')}")

    for section in sections[1:-1]:
        lines.extend(["", f"## {section}"])
        for signal in signals:
            action = signal.get("suggested_action") or "Review with the account or strategy lead."
            relevance = signal.get("client_relevance") or signal.get("why_it_matters", "")
            lines.append(f"- {action} {relevance}".strip())

    lines.extend(["", f"## {sections[-1]}"])
    for index, signal in enumerate(signals, start=1):
        source = signal.get("source", {})
        if not isinstance(source, dict):
            source = {}
        source_label = source.get("title") or source.get("url") or "Source not recorded"
        lines.extend(
            [
                "",
                f"### {index}. {signal.get('what_happened', '')}",
                f"- Why it matters: {signal.get('why_it_matters', '')}",
                f"- Client relevance: {signal.get('client_relevance', '')}",
                f"- Suggested action: {signal.get('suggested_action', '')}",
                f"- Source: {source_label}",
                f"- URL: {source.get('url', '')}",
            ]
        )
    return "\n".join(lines).strip() + "\n"
