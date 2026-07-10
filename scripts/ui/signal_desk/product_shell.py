from __future__ import annotations

USER_WORKSPACE_TABS = ["Rooms", "Signals", "Saved", "Briefs"]

CONTROL_CENTER_TABS = [
    "Overview",
    "Task Management",
    "Channels",
    "Validation",
    "Logs",
    "Delivery Format",
    "Task Debug",
]


def normalize_product_mode(value: str) -> str:
    return "Control Center" if value == "Control Center" else "Signal Desk"
