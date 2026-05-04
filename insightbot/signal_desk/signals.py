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


def _candidate_to_signal(
    room_id: str,
    run_id: str,
    candidate: dict[str, Any],
) -> SignalItem | None:
    what_happened = str(
        candidate.get("what_happened")
        or candidate.get("title")
        or candidate.get("summary")
        or ""
    ).strip()
    summary = str(candidate.get("summary") or "").strip()
    why_it_matters = str(candidate.get("why_it_matters") or summary).strip()
    candidate_id = str(candidate.get("id") or "").strip()
    source_url = str(candidate.get("url") or "").strip()
    signal_key = candidate_id or what_happened or summary or source_url
    if not signal_key:
        return None

    source: dict[str, str] = {}
    if source_url:
        source["url"] = source_url
    if candidate.get("published_at"):
        source["published_at"] = str(candidate["published_at"])

    return SignalItem(
        id=_make_signal_id(room_id, run_id, signal_key),
        room_id=room_id,
        run_id=run_id,
        what_happened=what_happened,
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
        why_it_matters="Fallback signal extracted from the final markdown output.",
        client_relevance="Needs manual review against the briefing room context.",
        suggested_action="Review the full run output before saving or escalating this signal.",
        judgement_lens=["manual_review"],
        source={},
        confidence="low",
        save_tags=["fallback"],
        raw_candidate_ref="",
    )


def signal_items_from_run_result(
    room_id: str,
    run_id: str,
    run_result: dict[str, Any],
) -> list[SignalItem]:
    stage_results = run_result.get("stage_results")
    shortlist = stage_results.get("shortlist") if isinstance(stage_results, dict) else []
    if isinstance(shortlist, list):
        structured_signals: list[SignalItem] = []
        for candidate in shortlist:
            if not isinstance(candidate, dict):
                continue
            signal = _candidate_to_signal(room_id, run_id, candidate)
            if signal is not None:
                structured_signals.append(signal)
        if structured_signals:
            return structured_signals

    final_markdown = str(run_result.get("final_markdown") or "")
    fallback_signal = _markdown_to_signal(room_id, run_id, final_markdown)
    if fallback_signal is None:
        return []
    return [fallback_signal]
