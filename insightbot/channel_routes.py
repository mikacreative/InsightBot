from __future__ import annotations

from typing import Any


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def normalize_channel_routes(
    raw_routes: list[Any] | None,
    channels_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize legacy channel ids and rich route objects into one shape."""
    normalized: list[dict[str, Any]] = []

    for item in raw_routes or []:
        if isinstance(item, str):
            channel_id = item.strip()
            if channel_id:
                normalized.append(
                    {
                        "channel_id": channel_id,
                        "enabled": True,
                        "audience": "",
                        "purpose": "default",
                    }
                )
            continue

        if not isinstance(item, dict):
            continue

        if not bool(item.get("enabled", True)):
            continue

        channel_id = _clean_text(item.get("channel_id") or item.get("id"))
        if not channel_id:
            continue

        route = {
            "channel_id": channel_id,
            "enabled": True,
            "audience": _clean_text(item.get("audience") or item.get("recipient")),
            "purpose": _clean_text(item.get("purpose"), "default"),
        }
        if item.get("publication_status") is not None:
            route["publication_status"] = _clean_text(item.get("publication_status"), "published")
        if item.get("visibility") is not None:
            route["visibility"] = _clean_text(item.get("visibility"), "audience")
        normalized.append(route)

    return normalized


def route_channel_ids(routes: list[dict[str, Any]]) -> list[str]:
    return [route["channel_id"] for route in routes if route.get("channel_id")]
