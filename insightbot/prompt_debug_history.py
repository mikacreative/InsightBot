import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import prompt_debug_history_file_path

MAX_HISTORY_ITEMS = 20


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_prompt_debug_history(bot_dir: str) -> list[dict[str, Any]]:
    path = Path(prompt_debug_history_file_path(bot_dir))
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_prompt_debug_history(bot_dir: str, items: list[dict[str, Any]]) -> str:
    path = Path(prompt_debug_history_file_path(bot_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def append_prompt_debug_history(bot_dir: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    history = load_prompt_debug_history(bot_dir)
    history.insert(0, record)
    trimmed = history[:MAX_HISTORY_ITEMS]
    save_prompt_debug_history(bot_dir, trimmed)
    return trimmed


def make_draft_run_record(
    *,
    task_id: str | None = None,
    task_name: str | None = None,
    category: str,
    candidate_count: int,
    result: dict[str, Any],
    using_fallback_candidates: bool,
    draft_prompt: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "task_id": task_id,
        "task_name": task_name,
        "category": category,
        "mode": "draft_run",
        "candidate_count": candidate_count,
        "saved_selected_count": None,
        "draft_selected_count": len(result.get("selected_items", [])),
        "draft_status": result.get("status"),
        "saved_status": None,
        "using_fallback_candidates": using_fallback_candidates,
        "draft_prompt_excerpt": draft_prompt.strip()[:120],
    }


def make_compare_record(
    *,
    task_id: str | None = None,
    task_name: str | None = None,
    category: str,
    candidate_count: int,
    saved_result: dict[str, Any],
    draft_result: dict[str, Any],
    using_fallback_candidates: bool,
    draft_prompt: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "task_id": task_id,
        "task_name": task_name,
        "category": category,
        "mode": "compare",
        "candidate_count": candidate_count,
        "saved_selected_count": len(saved_result.get("selected_items", [])),
        "draft_selected_count": len(draft_result.get("selected_items", [])),
        "draft_status": draft_result.get("status"),
        "saved_status": saved_result.get("status"),
        "using_fallback_candidates": using_fallback_candidates,
        "draft_prompt_excerpt": draft_prompt.strip()[:120],
    }
