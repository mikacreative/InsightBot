from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .paths import web_archive_file_path

PUBLISHED = "published"
PUBLIC_VISIBILITY = "public"
AUDIENCE_VISIBILITY = "audience"


def _archive_path(bot_dir: str | None = None) -> Path:
    return Path(web_archive_file_path(bot_dir))


def _make_record_id(record: dict[str, Any]) -> str:
    basis = "|".join(
        [
            str(record.get("task_id", "")),
            str(record.get("channel_id", "")),
            str(record.get("created_at", "")),
            str(record.get("title", "")),
        ]
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _normalize_audiences(record: dict[str, Any]) -> list[str]:
    raw = record.get("audiences")
    if raw is None:
        raw = record.get("audience", "")

    values: list[Any]
    if isinstance(raw, list):
        values = raw
    else:
        values = [raw]

    audiences: list[str] = []
    for value in values:
        for part in str(value or "").replace("，", ",").split(","):
            audience = part.strip()
            if audience and audience not in audiences:
                audiences.append(audience)
    return audiences


def _normalize_archive_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    audiences = _normalize_audiences(payload)
    payload["audiences"] = audiences
    payload.setdefault("audience", audiences[0] if audiences else "")
    payload.setdefault("publication_status", PUBLISHED)
    payload.setdefault(
        "visibility",
        AUDIENCE_VISIBILITY if audiences else PUBLIC_VISIBILITY,
    )
    payload.setdefault("record_id", _make_record_id(payload))
    return payload


def append_archive_record(bot_dir: str | None, record: dict[str, Any]) -> str:
    payload = _normalize_archive_record(record)

    path = _archive_path(bot_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return str(payload["record_id"])


def _load_archive_records(bot_dir: str | None = None) -> list[dict[str, Any]]:
    path = _archive_path(bot_dir)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(_normalize_archive_record(item))
    return records


def _parse_archive_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def _record_visible_to_audience(record: dict[str, Any], audience: str | None) -> bool:
    if not audience:
        return True
    if record.get("visibility") == PUBLIC_VISIBILITY:
        return True
    return audience in _normalize_audiences(record)


def _record_visible_to_audiences(record: dict[str, Any], audiences: list[str] | None) -> bool:
    if not audiences:
        return True
    if record.get("visibility") == PUBLIC_VISIBILITY:
        return True
    record_audiences = set(_normalize_audiences(record))
    return any(audience in record_audiences for audience in audiences)


def list_archive_records(
    *,
    bot_dir: str | None = None,
    task_id: str | None = None,
    channel_id: str | None = None,
    audience: str | None = None,
    audiences: list[str] | None = None,
    start_at: str | datetime | None = None,
    end_at: str | datetime | None = None,
    include_unpublished: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    records = _load_archive_records(bot_dir)
    start_dt = _parse_archive_datetime(start_at) if start_at is not None else None
    end_dt = _parse_archive_datetime(end_at) if end_at is not None else None

    if task_id:
        records = [item for item in records if item.get("task_id") == task_id]
    if channel_id:
        records = [item for item in records if item.get("channel_id") == channel_id]
    if not include_unpublished:
        records = [item for item in records if item.get("publication_status") == PUBLISHED]
    if audiences:
        records = [item for item in records if _record_visible_to_audiences(item, audiences)]
    if audience:
        records = [item for item in records if _record_visible_to_audience(item, audience)]
    if start_dt or end_dt:
        normalized_records: list[dict[str, Any]] = []
        for item in records:
            created = _parse_archive_datetime(item.get("created_at"))
            if not created:
                continue
            if start_dt and created < start_dt:
                continue
            if end_dt and created > end_dt:
                continue
            normalized_records.append(item)
        records = normalized_records

    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    if limit > 0:
        return records[:limit]
    return records


def get_archive_record(record_id: str, bot_dir: str | None = None) -> dict[str, Any] | None:
    for record in _load_archive_records(bot_dir):
        if record.get("record_id") == record_id:
            return record
    return None


def update_archive_record_publication(
    record_id: str,
    *,
    bot_dir: str | None = None,
    publication_status: str | None = None,
    visibility: str | None = None,
    audiences: list[str] | None = None,
) -> bool:
    path = _archive_path(bot_dir)
    records = _load_archive_records(bot_dir)
    updated = False
    rewritten: list[dict[str, Any]] = []

    for record in records:
        payload = dict(record)
        if payload.get("record_id") == record_id:
            if publication_status is not None:
                payload["publication_status"] = publication_status
            if visibility is not None:
                payload["visibility"] = visibility
            if audiences is not None:
                payload["audiences"] = audiences
                payload["audience"] = audiences[0] if audiences else ""
            updated = True
        rewritten.append(_normalize_archive_record(payload))

    if not updated:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for record in rewritten:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp_path.replace(path)
    return True


def find_archive_record_index(records: list[dict[str, Any]], record_id: str) -> int:
    if not record_id:
        return 0
    for idx, record in enumerate(records):
        if record.get("record_id") == record_id:
            return idx
    return 0
