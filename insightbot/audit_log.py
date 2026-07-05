from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import audit_log_file_path

SENSITIVE_KEYS = {
    "secret",
    "app_secret",
    "api_key",
    "webhook_url",
    "token",
    "token_hash",
    "password",
}


def _audit_path(bot_dir: str | None = None) -> Path:
    return Path(audit_log_file_path(bot_dir))


def redact_audit_changes(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = "***"
            else:
                redacted[key] = redact_audit_changes(item)
        return redacted
    if isinstance(value, list):
        return [redact_audit_changes(item) for item in value]
    return value


def append_audit_event(
    bot_dir: str | None,
    *,
    actor: dict[str, Any],
    action: str,
    target: dict[str, Any],
    changes: dict[str, Any],
    created_at: str | None = None,
) -> None:
    payload = {
        "created_at": created_at or datetime.now().isoformat(),
        "actor": {
            "name": actor.get("name", ""),
            "role": actor.get("role", ""),
        },
        "action": action,
        "target": target,
        "changes": redact_audit_changes(changes),
    }
    path = _audit_path(bot_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def list_audit_events(
    *,
    bot_dir: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    path = _audit_path(bot_dir)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)

    if action:
        events = [item for item in events if item.get("action") == action]
    events.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    if limit > 0:
        return events[:limit]
    return events
