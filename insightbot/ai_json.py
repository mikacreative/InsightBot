"""Helpers for parsing model JSON responses."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(raw: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a model response."""
    text = str(raw or "").strip()
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    decoder = json.JSONDecoder()
    candidates = [text]
    first_brace = text.find("{")
    if first_brace > 0:
        candidates.append(text[first_brace:])

    for candidate in candidates:
        try:
            data, _ = decoder.raw_decode(candidate.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None

