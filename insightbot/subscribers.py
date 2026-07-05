from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .paths import subscribers_file_path


PUBLIC_SUBSCRIBER = {
    "token": "",
    "name": "Public",
    "role": "subscriber",
    "audiences": ["public"],
}

LOCAL_ADMIN = {
    "token": "",
    "name": "Local Admin",
    "role": "admin",
    "audiences": ["public"],
}

ROLE_PERMISSIONS = {
    "subscriber": {"view_archive"},
    "operator": {"view_archive", "manage_publication", "run_tasks"},
    "admin": {
        "view_archive",
        "manage_publication",
        "run_tasks",
        "manage_channels",
        "manage_tasks",
        "manage_subscribers",
    },
}


def _normalize_audiences(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    audiences: list[str] = []
    for raw in raw_values:
        for part in str(raw or "").replace("，", ",").split(","):
            audience = part.strip()
            if audience and audience not in audiences:
                audiences.append(audience)
    return audiences or ["public"]


def hash_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def make_subscriber_record(
    *,
    token: str,
    name: str,
    role: str,
    audiences: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "audiences": _normalize_audiences(audiences),
        "token_hash": hash_token(token),
    }


def load_subscribers(bot_dir: str | None = None) -> dict[str, Any]:
    path = subscribers_file_path(bot_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"subscribers": {}}
    if not isinstance(data, dict):
        return {"subscribers": {}}
    data.setdefault("subscribers", {})
    return data


def save_subscribers(data: dict[str, Any], bot_dir: str | None = None) -> None:
    path = subscribers_file_path(bot_dir)
    tmp = path + ".tmp"
    payload = dict(data)
    payload.setdefault("subscribers", {})
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)


def resolve_subscriber(token: str | None, bot_dir: str | None = None) -> dict[str, Any]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return dict(PUBLIC_SUBSCRIBER)

    subscribers = load_subscribers(bot_dir).get("subscribers", {})
    payload = subscribers.get(normalized_token)
    if not isinstance(payload, dict):
        token_hash = hash_token(normalized_token)
        for item in subscribers.values():
            if isinstance(item, dict) and item.get("token_hash") == token_hash:
                payload = item
                break
    if not isinstance(payload, dict):
        return dict(PUBLIC_SUBSCRIBER)

    return {
        "token": normalized_token,
        "name": str(payload.get("name") or normalized_token),
        "role": str(payload.get("role") or "subscriber"),
        "audiences": _normalize_audiences(payload.get("audiences") or payload.get("audience")),
    }


def resolve_console_actor(
    token: str | None,
    bot_dir: str | None = None,
    auth_required: bool | None = None,
) -> dict[str, Any]:
    if not str(token or "").strip() and auth_required is False:
        return dict(LOCAL_ADMIN)
    if auth_required is None:
        auth_required = os.getenv("INSIGHTBOT_CONSOLE_AUTH_REQUIRED", "").strip() == "1"
    if not str(token or "").strip() and not auth_required:
        return dict(LOCAL_ADMIN)
    return resolve_subscriber(token, bot_dir=bot_dir)


def has_permission(actor: dict[str, Any], permission: str) -> bool:
    explicit = actor.get("permissions")
    if isinstance(explicit, list) and permission in explicit:
        return True
    role = str(actor.get("role") or "subscriber")
    return permission in ROLE_PERMISSIONS.get(role, set())
