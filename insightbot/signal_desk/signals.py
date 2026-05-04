from __future__ import annotations

import hashlib
import re
from typing import Any

from insightbot.signal_desk.models import SignalItem


def _make_signal_id(room_id: str, run_id: str, value: str) -> str:
    raw = f"{room_id}|{run_id}|{value}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _candidate_to_signal(room_id: str, run_id: str, candidate: dict[str, Any]) -> SignalItem:
    title = str(candidate.get("title") or candidate.get("summary") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    why_it_matters = str(candidate.get("why_it_matters") or summary).strip()
    candidate_id = str(candidate.get("id") or "").strip()
    signal_key = candidate_id or title or summary

    source: dict[str, str] = {}
    if candidate.get("url"):
        source["url"] = str(candidate["url"])
    if candidate.get("published_at"):
        source["published_at"] = str(candidate["published_at"])

    return SignalItem(
        id=_make_signal_id(room_id, run_id, signal_key),
        room_id=room_id,
        run_id=run_id,
        what_happened=title,
        why_it_matters=why_it_matters,
        client_relevance=str(candidate.get("client_relevance") or ""),
        suggested_action=str(candidate.get("suggested_action") or ""),
        judgement_lens=_as_string_list(candidate.get("judgement_lens")),
        source=source,
        confidence=str(candidate.get("confidence") or "medium"),
        save_tags=_as_string_list(candidate.get("save_tags")),
        raw_candidate_ref=candidate_id,
    )


def _markdown_to_signal(room_id: str, run_id: str, final_markdown: str) -> SignalItem | None:
    match = re.search(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", final_markdown, re.MULTILINE)
    if not match:
        return None

    heading = match.group(1).strip()
    return SignalItem(
        id=_make_signal_id(room_id, run_id, heading),
        room_id=room_id,
        run_id=run_id,
        what_happened=heading,
        why_it_matters="",
        client_relevance="",
        suggested_action="",
        judgement_lens=[],
        source={},
        confidence="low",
        save_tags=[],
        raw_candidate_ref="",
    )


def signal_items_from_run_result(room_id: str, run_id: str, run_result: dict[str, Any]) -> list[SignalItem]:
    shortlist = run_result.get("stage_results", {}).get("shortlist", [])
    if shortlist:
        return [
            _candidate_to_signal(room_id, run_id, candidate)
            for candidate in shortlist
            if isinstance(candidate, dict)
        ]

    final_markdown = str(run_result.get("final_markdown") or "")
    fallback_signal = _markdown_to_signal(room_id, run_id, final_markdown)
    if fallback_signal is None:
        return []
    return [fallback_signal]
