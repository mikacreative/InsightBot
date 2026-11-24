import os
import shlex
import socket
import subprocess
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/deploy-production.yml"
HEALTH_PATH = "/insightbot/_stcore/health"


def run_probe(tmp_path, port):
    invocation = next(
        line.strip()
        for line in WORKFLOW.read_text().splitlines()
        if line.strip().startswith("bash scripts/check_streamlit_health.sh")
    )
    shell, script, url = shlex.split(invocation)
    endpoint = urlsplit(url)
    assert (endpoint.scheme, endpoint.hostname, endpoint.port) == ("http", "127.0.0.1", 8501)

    # Keep the real curl and skip only the retry delay.
    sleep = tmp_path / "sleep"
    sleep.write_text('#!/bin/sh\n[ "$1" = 5 ]\n')
    sleep.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1"
    return subprocess.run(
        [shell, str(ROOT / script), endpoint._replace(netloc=f"127.0.0.1:{port}").geturl()],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


@pytest.mark.parametrize(
    ("responses", "attempts", "exit_code"),
    [
        ([200], 1, 0),
        ([404], 12, 1),
        ([500], 12, 1),
        ([302], 12, 1),
        ([500, 200], 2, 0),
    ],
)
def test_http_health_status(tmp_path, responses, attempts, exit_code):
    statuses = deque(responses)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/ready":
                self.send_response(200)
                self.end_headers()
                return
            self.send_response(statuses[0])
            if statuses[0] == 302:
                self.send_header("Location", "/ready")
            if len(statuses) > 1:
                statuses.popleft()
            self.end_headers()

        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            result = run_probe(tmp_path, server.server_port)
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == exit_code
    assert requests == [HEALTH_PATH] * attempts
    if responses[0] != 200:
        assert f"returned HTTP {responses[0]}" in result.stderr
    if exit_code:
        assert "failed after retries" in result.stderr


def test_connection_failure(tmp_path):
    # Release the port. A bound but unlistened socket can time out on macOS.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    result = run_probe(tmp_path, port)

    assert result.returncode == 1
    assert "attempt 12/12 failed (curl exit 7)" in result.stderr
    assert "failed after retries" in result.stderr
