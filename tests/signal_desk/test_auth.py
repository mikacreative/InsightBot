import json
import stat
import pytest
from insightbot.signal_desk.auth import Auth, RateLimitError


def test_bootstrap_and_hash_permissions(tmp_path):
    auth = Auth(tmp_path)
    password = (tmp_path / 'bootstrap-admin.txt').read_text().strip()
    stored = (tmp_path / 'users.json').read_text()
    assert password not in stored
    assert json.loads(stored)['admin']['password']['algorithm'] == 'pbkdf2_sha256'
    for name in ('users.json', 'bootstrap-admin.txt'):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600
    assert auth.authenticate('admin', password)['role'] == 'admin'
    assert Auth(tmp_path).authenticate('admin', password)
    assert (tmp_path / 'bootstrap-admin.txt').read_text().strip() == password


def test_create_account_and_no_password_reuse(tmp_path):
    auth = Auth(tmp_path)
    assert auth.create_user('Mika', 'different-password')['role'] == 'editor'
    assert auth.authenticate('mika', 'wrong') is None
    login = auth.authenticate('MIKA', 'different-password')
    assert login['username'] == 'mika' and login['role'] == 'editor'
    assert 'password' not in login
    with pytest.raises(ValueError): auth.create_user('mika', 'different-password')
    with pytest.raises(ValueError): auth.create_user('x', 'short')
    with pytest.raises(ValueError): auth.create_user('x', 'valid-long-password', 'owner')


def test_session_expiry_logout_csrf_and_restart(tmp_path):
    now = [1000]
    auth = Auth(tmp_path, session_ttl=60, clock=lambda: now[0])
    auth.create_user('staff', 'valid-long-password')
    one = auth.authenticate('staff', 'valid-long-password')
    two = auth.authenticate('staff', 'valid-long-password')
    assert one['token'] != two['token'] and one['csrf'] != two['csrf']
    assert auth.session('unknown') is None
    external = auth.session(one['token']); external['role'] = 'admin'
    assert auth.session(one['token'])['role'] == 'editor'
    auth.logout(one['token'])
    assert auth.session(one['token']) is None
    assert Auth(tmp_path).session(two['token']) is None
    now[0] += 60
    assert auth.session(two['token']) is None


def test_failed_login_rate_limit_and_release(tmp_path):
    now = [1000]
    auth = Auth(tmp_path, clock=lambda: now[0])
    for _ in range(5): assert auth.authenticate('missing', 'wrong', 'client') is None
    with pytest.raises(RateLimitError): auth.authenticate('admin', 'wrong', 'client')
    assert auth.authenticate('missing', 'wrong', 'other-client') is None
    now[0] += 901
    assert auth.authenticate('missing', 'wrong', 'client') is None


def test_valid_login_preserves_client_failure_history(tmp_path):
    now = [1000]
    auth = Auth(tmp_path, clock=lambda: now[0])
    auth.create_user('staff', 'fictional-staff-password')
    for _ in range(4):
        assert auth.authenticate('admin', 'wrong', 'client') is None
    assert auth.authenticate('staff', 'fictional-staff-password', 'client')
    assert auth.authenticate('admin', 'wrong', 'client') is None
    with pytest.raises(RateLimitError):
        auth.authenticate('admin', 'wrong', 'client')
    with pytest.raises(RateLimitError):
        auth.authenticate('staff', 'fictional-staff-password', 'client')
    assert auth.authenticate('staff', 'fictional-staff-password', 'other-client')
    now[0] += Auth.FAILURE_WINDOW
    assert auth.authenticate('staff', 'fictional-staff-password', 'client')


def test_password_rotation_invalidates_sessions_and_bootstrap(tmp_path):
    auth = Auth(tmp_path)
    password = (tmp_path / 'bootstrap-admin.txt').read_text().strip()
    login = auth.authenticate('admin', password)
    assert not auth.change_password('admin', 'wrong', 'new-long-password')
    assert auth.change_password('admin', password, 'new-long-password')
    assert auth.session(login['token']) is None
    assert not (tmp_path / 'bootstrap-admin.txt').exists()
    assert auth.authenticate('admin', password) is None
    assert auth.authenticate('admin', 'new-long-password')
    assert auth.users() == [{'username': 'admin', 'role': 'admin'}]
    restarted = Auth(tmp_path)
    assert not (tmp_path / 'bootstrap-admin.txt').exists()
    assert restarted.authenticate('admin', 'new-long-password')


def test_corrupt_account_store_fails_closed(tmp_path):
    (tmp_path / 'users.json').write_text('{}')
    with pytest.raises(ValueError): Auth(tmp_path)
    assert not (tmp_path / 'bootstrap-admin.txt').exists()
