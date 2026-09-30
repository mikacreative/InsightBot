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


def test_login_roles_origin_and_csrf(tmp_path):
    import httpx
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
    process=subprocess.Popen([sys.executable,'-m','insightbot.signal_desk','--state-dir',str(tmp_path),'serve','--port',str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        base=f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base,timeout=3,trust_env=False) as admin:
            for _ in range(100):
                try:
                    if admin.get('/health').status_code==200: break
                except httpx.HTTPError: time.sleep(.1)
            assert admin.get('/api/jobs').status_code==401
            assert admin.post('/api/login',json={'username':'admin','password':'x'},headers={'Origin':'https://evil.example'}).status_code==403
            login=admin.post('/api/login',json={'username':'admin','password':(tmp_path/'bootstrap-admin.txt').read_text().strip()})
            assert login.status_code==200
            assert 'HttpOnly' in login.headers['set-cookie'] and 'SameSite=Strict' in login.headers['set-cookie']
            csrf={'X-Signal-Desk-CSRF':login.json()['csrf']}
            assert admin.post('/api/profile',json={}).status_code==403
            assert admin.post('/api/users',json={'username':'editor','password':'fixture-long-password','role':'editor'},headers=csrf).status_code==200
            with httpx.Client(base_url=base,timeout=3,trust_env=False) as editor:
                user=editor.post('/api/login',json={'username':'editor','password':'fixture-long-password'}).json()
                assert editor.get('/api/users').status_code!=200
                assert editor.post('/api/users',json={'username':'evil','password':'fixture-long-password','role':'admin'},headers={'X-Signal-Desk-CSRF':user['csrf']}).status_code==403
                assert editor.get('/api/jobs').status_code==200
                assert editor.post('/api/logout',json={},headers={'X-Signal-Desk-CSRF':user['csrf']}).status_code==200
                assert editor.get('/api/jobs').status_code==401
    finally:
        process.terminate();process.wait(timeout=5)
