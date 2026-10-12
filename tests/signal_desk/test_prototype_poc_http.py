"""Real HTTP checks against disposable prototype state, never the live brand UI."""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def service(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html><title>Fictional local prototype</title>")
    auth = tmp_path / "engine-auth.json"
    auth.write_text(json.dumps({"username": "test-only", "password": "test-only"}))
    process = subprocess.Popen([sys.executable, "-m", "insightbot.signal_desk.prototype_poc", "--port", str(port),
                                "--state-dir", str(tmp_path / "state"), "--assets", str(assets),
                                "--engine-auth", str(auth), "--engine-url", "http://127.0.0.1:1"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if client.get("/health").status_code == 200:
                break
        except httpx.HTTPError:
            if process.poll() is not None:
                raise RuntimeError("Disposable prototype did not start")
            time.sleep(0.05)
    else:
        process.terminate()
        raise RuntimeError("Disposable prototype readiness timed out")
    try:
        yield client, tmp_path
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)


def test_host_origin_and_csrf_protect_local_mutations(service):
    client, _ = service
    state = client.get("/api/state").json()
    assert state["planner"]["mode"] == "demo"
    assert not state["engine"]["available"]
    assert client.get("/api/state", headers={"Host": "untrusted.example"}).status_code == 403
    body = {"plan": state["plan"], "expected_version": state["plan"]["version"]}
    assert client.post("/api/plan", json=body).status_code == 403
    assert client.post("/api/plan", headers={"X-Signal-Desk-CSRF": state["csrf"], "Origin": "https://untrusted.example"}, json=body).status_code == 403
    assert client.get("/api/state").json()["plan"] == state["plan"]


def test_canvas_invalid_edge_restores_plan_and_missing_callback_auth(service):
    client, _ = service
    state = client.get("/api/state").json()
    plan = state["plan"]
    plan["edges"].append({"id": "bypass_review", "source": "summary", "target": "publish"})
    response = client.post("/api/plan", headers={"X-Signal-Desk-CSRF": state["csrf"]},
                           json={"plan": plan, "expected_version": 1})
    assert response.status_code == 400
    assert client.get("/api/state").json()["plan"]["version"] == 1
    assert client.post("/internal/executions/guessed/nodes/publish", json={}).status_code == 403


def test_private_workspace_not_served_and_no_callback_secret_in_state(service):
    client, tmp_path = service
    response = client.get("/")
    assert response.status_code == 200 and "Fictional" in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    saved = json.loads((tmp_path / "state/workspace.json").read_text())
    public = client.get("/api/state").text
    assert saved["callback_token"] not in public
    assert client.get("/workspace.json").status_code == 404
    assert client.get("/../state/workspace.json").status_code == 404


def test_past_once_schedule_rejected_without_changing_version(service):
    client, _ = service
    state = client.get("/api/state").json()
    response = client.post("/api/schedule", headers={"X-Signal-Desk-CSRF": state["csrf"]},
                           json={"expected_version": 1, "schedule": {"enabled": True, "mode": "once", "at": "2000-01-01T09:00:00+08:00"}})
    assert response.status_code == 400
    latest = client.get("/api/state").json()
    assert latest["plan"]["version"] == 1 and not latest["plan"]["schedule"]["enabled"]
