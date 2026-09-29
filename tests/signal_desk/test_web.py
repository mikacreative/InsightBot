"""A browser preconnect must not monopolize the health/UI server."""
import socket
import subprocess
import sys
import time
import urllib.request


def test_idle_browser_connection_does_not_block_health(tmp_path):
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    process = subprocess.Popen([sys.executable, '-m', 'insightbot.signal_desk', '--state-dir', str(tmp_path),
                                'serve', '--port', str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    idle = None
    try:
        for _ in range(100):
            try:
                idle = socket.create_connection(('127.0.0.1', port), timeout=.2)
                break
            except OSError:
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read().decode())
                time.sleep(.1)
        assert idle is not None
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as response:
            assert response.status == 200
            assert b'local-only' in response.read()
    finally:
        if idle:
            idle.close()
        process.terminate()
        process.wait(timeout=5)
