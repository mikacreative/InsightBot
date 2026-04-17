import json
from pathlib import Path
from typing import Any

from .paths import task_health_cache_file_path


def load_task_health(task_id: str, bot_dir: str | None = None) -> dict[str, Any] | None:
    path = Path(task_health_cache_file_path(task_id, bot_dir))
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_task_health(snapshot: dict[str, Any], task_id: str, bot_dir: str | None = None) -> str:
    path = Path(task_health_cache_file_path(task_id, bot_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def clear_task_health(task_id: str, bot_dir: str | None = None) -> None:
    path = Path(task_health_cache_file_path(task_id, bot_dir))
    if path.exists():
        path.unlink()
