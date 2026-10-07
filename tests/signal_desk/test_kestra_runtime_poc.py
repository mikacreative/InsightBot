"""Safety checks for the disposable, local Kestra launcher."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "scripts/signal-desk-kestra-runtime.py"
SPEC = importlib.util.spec_from_file_location("signal_desk_kestra_runtime", SOURCE)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def test_checksum_mismatch_never_installs_download(tmp_path, monkeypatch):
    class Response(io.BytesIO):
        pass

    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *args, **kwargs: Response(b"corrupted"))
    target = tmp_path / "downloads/artifact.zip"
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        runtime.download("https://example.invalid/artifact", target, "sha256", hashlib.sha256(b"expected").hexdigest())
    assert not target.exists()
    assert not target.with_suffix(".zip.partial").exists()


def test_cached_artifact_is_verified_before_reuse(tmp_path, monkeypatch):
    target = tmp_path / "artifact.zip"
    target.write_bytes(b"verified")
    def unexpected_network(*args, **kwargs):
        raise AssertionError("valid pinned artifact should not be downloaded again")
    monkeypatch.setattr(runtime.urllib.request, "urlopen", unexpected_network)
    runtime.download("https://example.invalid/artifact", target, "sha256", hashlib.sha256(b"verified").hexdigest())


def test_api_credentials_are_private_stable_and_absent_from_configuration(tmp_path):
    auth = runtime.credentials(tmp_path)
    assert runtime.credentials(tmp_path) == auth
    assert stat.S_IMODE((tmp_path / "api-auth.json").stat().st_mode) == 0o600
    config_path = runtime.write_configuration(tmp_path, auth)
    source = config_path.read_text()
    config = json.loads(source)
    assert auth["password"] not in source
    assert auth["encryption_key"] not in source
    assert config["micronaut"]["server"]["host"] == "127.0.0.1"
    assert config["endpoints"]["all"]["bind-host"] == "127.0.0.1"
    assert config["kestra"]["anonymous-usage-report"]["enabled"] is False
    assert config["kestra"]["ui-anonymous-usage-report"]["enabled"] is False
    assert config["kestra"]["plugins"]["auto-install"]["enabled"] is False
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_stop_never_signals_pid_reused_by_another_service(tmp_path, monkeypatch):
    (tmp_path / "runtime.pid").write_text("12345\n")
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout="/usr/bin/unrelated-service\n"))
    def unexpected_kill(*args, **kwargs):
        raise AssertionError("launcher must not kill a reused PID")
    monkeypatch.setattr(runtime.os, "kill", unexpected_kill)
    result = runtime.stop(tmp_path)
    assert result["running"] is False
    assert not (tmp_path / "runtime.pid").exists()


def test_occupied_port_is_reported_before_any_bootstrap_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "process_id", lambda *args: None)
    def occupied():
        raise RuntimeError("localhost:18978 is already occupied")
    monkeypatch.setattr(runtime, "check_ports", occupied)
    def unexpected_prepare(*args):
        raise AssertionError("occupied port must stop before installing or creating state")
    monkeypatch.setattr(runtime, "prepare", unexpected_prepare)
    with pytest.raises(RuntimeError, match="already occupied"):
        runtime.start(tmp_path, 1)
