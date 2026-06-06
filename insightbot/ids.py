"""Identifier validation helpers for runtime config keys."""

import re

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_safe_id(value: str) -> bool:
    return bool(ID_PATTERN.fullmatch(str(value or "")))


def require_safe_id(value: str, *, label: str = "id") -> str:
    candidate = str(value or "").strip()
    if not is_safe_id(candidate):
        raise ValueError(f"{label} must match [A-Za-z0-9_-] and be 1-64 characters long.")
    return candidate
