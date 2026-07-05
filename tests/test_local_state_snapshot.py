import json
import subprocess
import sys
from pathlib import Path

from insightbot.paths import tasks_file_path, channels_file_path, subscribers_file_path, audit_log_file_path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_snapshot_reports_existing_core_files(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_BOT_DIR", str(tmp_path))

    _write_json(Path(tasks_file_path(str(tmp_path))), {"tasks": {"daily": {}}})
    _write_json(Path(channels_file_path(str(tmp_path))), {"channels": {}})
    # subscribers and audit_log intentionally absent to mimic local baseline state
    _write_json(Path(subscribers_file_path(str(tmp_path))), {"subscribers": {}})
    audit_log_path = Path(audit_log_file_path(str(tmp_path)))
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_log_path.write_text("", encoding="utf-8")

    cmd = [sys.executable, "scripts/local_state_snapshot.py", "--bot-dir", str(tmp_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    data = json.loads(proc.stdout)
    assert proc.returncode == 0
    assert data["files"]["tasks"]["exists"] is True
    assert data["files"]["channels"]["exists"] is True
    assert data["files"]["subscribers"]["exists"] is True
    assert data["files"]["audit_log"]["exists"] is True
    assert data["required_check"]["status"] == "ok"


def test_snapshot_can_detect_missing_required_files(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_BOT_DIR", str(tmp_path))
    Path(tasks_file_path(str(tmp_path))).parent.mkdir(parents=True, exist_ok=True)
    _write_json(Path(tasks_file_path(str(tmp_path))), {"tasks": {}})
    _write_json(Path(channels_file_path(str(tmp_path))), {"channels": {}})

    proc = subprocess.run(
        [sys.executable, "scripts/local_state_snapshot.py", "--bot-dir", str(tmp_path), "--require", "subscribers"],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert data["required_check"]["status"] == "failed"
    assert "subscribers" in data["required_check"]["missing_or_invalid"]


def test_snapshot_strict_is_limited_to_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_BOT_DIR", str(tmp_path))
    Path(tasks_file_path(str(tmp_path))).parent.mkdir(parents=True, exist_ok=True)
    _write_json(Path(tasks_file_path(str(tmp_path))), {"tasks": {}})
    _write_json(Path(channels_file_path(str(tmp_path))), {"channels": {}})

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/local_state_snapshot.py",
            "--bot-dir",
            str(tmp_path),
            "--require",
            "tasks",
            "channels",
            "--strict",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(proc.stdout)
    assert proc.returncode == 0
    assert data["required_check"]["status"] == "ok"
    assert "subscribers" not in data["required_check"]["items"]
    assert data["files"]["subscribers"]["exists"] is False
    assert data["files"]["audit_log"]["exists"] is False
    assert data["required_check"]["missing_or_invalid"] == []


def test_snapshot_diff_with_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_BOT_DIR", str(tmp_path))
    _write_json(Path(tasks_file_path(str(tmp_path))), {"tasks": {"daily": {}}})
    _write_json(Path(channels_file_path(str(tmp_path))), {"channels": {}})
    _write_json(Path(subscribers_file_path(str(tmp_path))), {"subscribers": {}})
    audit_log_path = Path(audit_log_file_path(str(tmp_path)))
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_log_path.write_text("", encoding="utf-8")

    baseline_path = tmp_path / "baseline.json"
    first = subprocess.run(
        [sys.executable, "scripts/local_state_snapshot.py", "--bot-dir", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    baseline_path.write_text(first.stdout, encoding="utf-8")

    # modify one tracked file
    _write_json(Path(tasks_file_path(str(tmp_path))), {"tasks": {"daily": {"feeds": {}}}})

    second = subprocess.run(
        [sys.executable, "scripts/local_state_snapshot.py", "--bot-dir", str(tmp_path), "--baseline", str(baseline_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(second.stdout)
    assert data["baseline_diff"]["status"] == "changed"
    assert any("tasks:sha256_changed" in item for item in data["baseline_diff"]["items"])
    assert second.returncode == 0


def test_snapshot_strict_fails_when_baseline_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_BOT_DIR", str(tmp_path))
    _write_json(Path(tasks_file_path(str(tmp_path))), {"tasks": {}})
    _write_json(Path(channels_file_path(str(tmp_path))), {"channels": {}})

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/local_state_snapshot.py",
            "--bot-dir",
            str(tmp_path),
            "--strict",
            "--baseline",
            str(tmp_path / "nonexistent-baseline.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert data["baseline_diff"]["status"] == "baseline_not_found"
