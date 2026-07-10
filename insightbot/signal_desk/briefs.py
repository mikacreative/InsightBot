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


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _signal_title(signal: dict) -> str:
    return _clean_text(signal.get("what_happened")) or _clean_text(signal.get("title")) or "Untitled signal"


def _source_payload(signal: dict) -> dict:
    source = signal.get("source", {})
    return source if isinstance(source, dict) else {}


def _source_label(signal: dict) -> str:
    source = _source_payload(signal)
    return _clean_text(source.get("title")) or _clean_text(source.get("url")) or "Source not recorded"


def _append_unique_bullet(lines: list[str], seen: set[str], text: str) -> None:
    bullet = _clean_text(text)
    if not bullet or bullet in seen:
        return
    seen.add(bullet)
    lines.append(f"- {bullet}")


def _section_bullet(section: str, signal: dict) -> str:
    title = _signal_title(signal)
    why_it_matters = _clean_text(signal.get("why_it_matters"))
    client_relevance = _clean_text(signal.get("client_relevance"))
    suggested_action = _clean_text(signal.get("suggested_action"))
    source_label = _source_label(signal)

    if section == "Executive takeaways":
        if not _clean_text(signal.get("what_happened")) and not why_it_matters:
            return ""
        return f"{title}: {why_it_matters}" if why_it_matters else title
    if section == "Client conversation starters":
        relevance = client_relevance or why_it_matters or "Review potential client relevance with the account lead."
        return f"{title}: {relevance}"
    if section == "Recommended next actions":
        return suggested_action or f"Review with the account or strategy lead: {title}"
    if section == "Pitch angles":
        action = suggested_action or "Explore as a pitch angle"
        return f"Angle: {action} Build from {title}."
    if section == "Proof points":
        evidence = why_it_matters or "No implication recorded"
        return f"{title}: {evidence} Evidence source: {source_label}."
    if section == "Inspiration hooks":
        hook = client_relevance or why_it_matters or "Review for reusable creative or strategic inspiration."
        return f"Inspiration hook from {title}: {hook}"
    if section == "Reusable references":
        return f"Reuse reference: {title}. Source: {source_label}."
    if section == "Trend observations":
        observation = why_it_matters or "Track whether this develops into a broader market pattern."
        return f"Observation: {title}. {observation}"
    if section == "Implications":
        implication = client_relevance or why_it_matters or "Review implications with the account or strategy lead."
        return f"Implication from {title}: {implication}"
    return ""


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
    seen: set[str] = set()
    for signal in signals:
        _append_unique_bullet(lines, seen, _section_bullet(sections[0], signal))

    for section in sections[1:-1]:
        lines.extend(["", f"## {section}"])
        seen = set()
        for signal in signals:
            _append_unique_bullet(lines, seen, _section_bullet(section, signal))

    lines.extend(["", f"## {sections[-1]}"])
    for index, signal in enumerate(signals, start=1):
        source = _source_payload(signal)
        detail_lines = [
            "",
            f"### {index}. {_signal_title(signal)}",
        ]
        for label, value in [
            ("Why it matters", signal.get("why_it_matters")),
            ("Client relevance", signal.get("client_relevance")),
            ("Suggested action", signal.get("suggested_action")),
        ]:
            text = _clean_text(value)
            if text:
                detail_lines.append(f"- {label}: {text}")
        detail_lines.append(f"- Source: {_source_label(signal)}")
        url = _clean_text(source.get("url"))
        if url:
            detail_lines.append(f"- URL: {url}")
        lines.extend(detail_lines)
    return "\n".join(lines).strip() + "\n"
