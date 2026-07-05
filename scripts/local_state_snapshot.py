#!/usr/bin/env python3
"""
Generate and validate local runtime snapshots for dev-editorial.

Usage:
  python scripts/local_state_snapshot.py
  python scripts/local_state_snapshot.py --bot-dir /path/to/bot --baseline path/to/baseline.json --strict
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from insightbot.paths import (
    audit_log_file_path,
    default_bot_dir,
    channels_file_path,
    subscribers_file_path,
    tasks_file_path,
)


def sha256_text(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return {}, f"json_decode_error: {e}"
    except Exception as e:
        return {}, f"json_read_error: {e}"


def _read_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return sum(1 for _line in f)


def _build_file_state(path: Path) -> dict[str, Any]:
    raw = path.read_bytes() if path.exists() else b""
    state: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": len(raw),
    }
    if not path.exists():
        state["status"] = "missing"
        return state

    state["sha256"] = sha256_text(raw)

    if path.suffix == ".json":
        payload, error = _read_json(path)
        state["parsed"] = "json"
        state["top_level_type"] = type(payload).__name__
        if isinstance(payload, dict):
            state["top_level_keys"] = list(payload.keys())
        if error:
            state["parse_error"] = error
            state["status"] = "parse_error"
        else:
            state["status"] = "ok"
        return state

    if path.suffix == ".jsonl":
        state["parsed"] = "jsonl"
        state["line_count"] = _read_jsonl_count(path)
        state["status"] = "ok"
        return state

    state["status"] = "ok"
    return state


def _collect_snapshot(bot_dir: str) -> dict[str, Any]:
    mapping = {
        "tasks": tasks_file_path(bot_dir),
        "channels": channels_file_path(bot_dir),
        "subscribers": subscribers_file_path(bot_dir),
        "audit_log": audit_log_file_path(bot_dir),
    }

    files: dict[str, Any] = {}
    for key, path in mapping.items():
        files[key] = _build_file_state(Path(path))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bot_dir": bot_dir,
        "files": files,
    }


def _diff_snapshots(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    current_files = current.get("files", {})
    base_files = baseline.get("files", {})
    for key in sorted(set(current_files) | set(base_files)):
        curr = current_files.get(key, {})
        base = base_files.get(key, {})
        if curr.get("status") == "missing" and base.get("status") == "missing":
            continue
        if curr.get("sha256") != base.get("sha256"):
            diffs.append(f"{key}:sha256_changed")
        if curr.get("exists") != base.get("exists"):
            diffs.append(f"{key}:existence_changed")
        if curr.get("top_level_keys", []) != base.get("top_level_keys", []):
            diffs.append(f"{key}:top_level_keys_changed")
    return diffs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local runtime state snapshot utility")
    parser.add_argument("--bot-dir", default=default_bot_dir(), help="InsightBot working directory")
    parser.add_argument(
        "--require",
        nargs="+",
        choices=("tasks", "channels", "subscribers", "audit_log"),
        default=[],
        help="Fail if required files are missing or parse-failed",
    )
    parser.add_argument("--baseline", default="", help="Path to baseline snapshot JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any consistency diff against baseline",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON output indentation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = _collect_snapshot(args.bot_dir)

    baseline_path = Path(args.baseline) if args.baseline else None
    if baseline_path:
        if baseline_path.exists():
            baseline, err = _read_json(baseline_path)
            if err:
                print(f"[ERROR] Failed to read baseline: {err}")
                return 2
            diff_items = _diff_snapshots(snapshot, baseline)
            snapshot["baseline_diff"] = {
                "path": str(baseline_path),
                "items": diff_items,
                "count": len(diff_items),
                "status": "ok" if not diff_items else "changed",
            }
        else:
            snapshot["baseline_diff"] = {
                "path": str(baseline_path),
                "status": "baseline_not_found",
            }

    required_missing = []
    for key in args.require:
        file_state = snapshot["files"].get(key, {})
        if not file_state.get("exists") or not file_state.get("status", "").startswith("ok"):
            required_missing.append(key)

    snapshot["required_check"] = {
        "items": args.require,
        "missing_or_invalid": required_missing,
        "status": "ok" if not required_missing else "failed",
    }

    # Keep stdout machine-readable for CI/local automation.
    print(json.dumps(snapshot, ensure_ascii=False, indent=args.indent, sort_keys=True))

    if required_missing:
        return 1
    if args.strict and snapshot.get("baseline_diff", {}).get("status") not in (None, "ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
