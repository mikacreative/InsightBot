import hashlib
import json
from pathlib import Path
from typing import Any

from .paths import task_state_file_path


def build_task_revision(runtime_config: dict[str, Any]) -> str:
    tracked = {
        "sources": runtime_config.get("sources", {}),
        "sections": runtime_config.get("sections", {}),
        "settings": runtime_config.get("settings", {}),
        "ai": {
            "system_prompt": (runtime_config.get("ai", {}) or {}).get("system_prompt", ""),
            "selection": (runtime_config.get("ai", {}) or {}).get("selection", {}),
            "editorial_pipeline": (runtime_config.get("ai", {}) or {}).get("editorial_pipeline", {}),
        },
        "task_pipeline": runtime_config.get("_task_pipeline"),
        "task_channels": runtime_config.get("_task_channels", []),
    }
    raw = json.dumps(tracked, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def load_task_state(task_id: str, bot_dir: str | None = None) -> dict[str, Any]:
    path = Path(task_state_file_path(task_id, bot_dir))
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_task_state(state: dict[str, Any], task_id: str, bot_dir: str | None = None) -> str:
    path = Path(task_state_file_path(task_id, bot_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def touch_revalidation_state(
    *,
    task_id: str,
    config_revision: str,
    needs_revalidation: bool,
    bot_dir: str | None = None,
    last_validated_revision: str | None = None,
) -> dict[str, Any]:
    state = load_task_state(task_id, bot_dir)
    state["task_id"] = task_id
    state["config_revision"] = config_revision
    state["needs_revalidation"] = needs_revalidation
    if last_validated_revision is not None:
        state["last_validated_revision"] = last_validated_revision
    save_task_state(state, task_id, bot_dir)
    return state
