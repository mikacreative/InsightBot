import json
from pathlib import Path
from typing import Any

from .paths import task_runs_file_path


def _history_path(bot_dir: str | None = None) -> Path:
    return Path(task_runs_file_path(bot_dir))


def append_run_record(bot_dir: str | None, record: dict[str, Any]) -> str:
    path = _history_path(bot_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return str(path)


def _load_records(bot_dir: str | None = None) -> list[dict[str, Any]]:
    path = _history_path(bot_dir)
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
            records.append(item)
    return records


def list_task_runs(task_id: str, bot_dir: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    records = [item for item in _load_records(bot_dir) if item.get("task_id") == task_id]
    records.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    if limit > 0:
        return records[:limit]
    return records


def get_latest_run(task_id: str, bot_dir: str | None = None) -> dict[str, Any] | None:
    runs = list_task_runs(task_id, bot_dir=bot_dir, limit=1)
    return runs[0] if runs else None


def get_latest_successful_send(task_id: str, bot_dir: str | None = None) -> dict[str, Any] | None:
    for item in list_task_runs(task_id, bot_dir=bot_dir, limit=0):
        if item.get("dry_run"):
            continue
        channel_results = item.get("channel_results", [])
        if any(isinstance(result, dict) and result.get("ok") for result in channel_results):
            return item
    return None
