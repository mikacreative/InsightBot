"""Local test accounts and revocable sessions; HTTP authorization lives in web.py.

Auth.authenticate returns None on bad credentials, raises RateLimitError after
five failed attempts per client within fifteen minutes. Session dictionaries
contain token, csrf, username, role and expires_at; never persist or log them.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time


class RateLimitError(ValueError):
    pass


class Auth:
    ITERATIONS = 600_000
    FAILURE_WINDOW = 900
    MAX_FAILURES = 5

    def __init__(self, state_dir, session_ttl=28_800, clock=None):
        if session_ttl <= 0:
            raise ValueError('Session lifetime must be positive')
        self.root = Path(state_dir)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'users.json'
        self.clock = clock or time.time
        self.session_ttl = session_ttl
        self.lock = threading.RLock()
        self.sessions = {}
        self.failures = {}
        self.dummy = self._hash(secrets.token_urlsafe(24))
        if self.path.exists():
            self._users = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self._users, dict) or not self._users:
                raise ValueError('Invalid account store; refusing to re-bootstrap')
            os.chmod(self.path, 0o600)
        else:
            self._users = {}
            password = secrets.token_urlsafe(24)
            bootstrap = self.root / 'bootstrap-admin.txt'
            # Never overwrite a prior bootstrap secret if setup was interrupted.
            if bootstrap.exists():
                password = bootstrap.read_text(encoding='utf-8').strip()
            else:
                fd = os.open(bootstrap, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(password + '\n')
            os.chmod(bootstrap, 0o600)
            self.create_user('admin', password, 'admin')

    @classmethod
    def _hash(cls, password):
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), cls.ITERATIONS).hex()
        return {'algorithm': 'pbkdf2_sha256', 'iterations': cls.ITERATIONS, 'salt': salt, 'digest': digest}

    @staticmethod
    def _verify(password, record):
        if not isinstance(password, str) or len(password) > 1024:
            return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(record['salt']), record['iterations']).hex()
        return hmac.compare_digest(digest, record['digest'])

    def _save(self):
        temporary = self.root / ('users-' + secrets.token_hex(8) + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self._users, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def create_user(self, username, password, role='editor'):
        """Caller must authorize admin role before invoking this method."""
        if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', username):
            raise ValueError('Username must contain 1-64 ASCII letters, digits, dot, underscore or hyphen')
        username = username.lower()
        if role not in ('admin', 'editor'):
            raise ValueError('Role must be admin or editor')
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise ValueError('Password must contain 12-1024 characters')
        with self.lock:
            if username in self._users:
                raise ValueError('Username already exists')
            record = {'role': role, 'password': self._hash(password)}
            self._users[username] = record
            try:
                self._save()
            except Exception:
                del self._users[username]
                raise
            return {'username': username, 'role': role}

    def authenticate(self, username, password, client_id=''):
        with self.lock:
            now = self.clock()
            # Drop old buckets to bound retention, including abandoned clients.
            self.failures = {key: [t for t in times if now - t < self.FAILURE_WINDOW]
                             for key, times in self.failures.items() if times and now - times[-1] < self.FAILURE_WINDOW}
            bucket = str(client_id)[:256]
            attempts = self.failures.get(bucket, [])
            if len(attempts) >= self.MAX_FAILURES:
                raise RateLimitError('Too many login attempts; try again later')
            username = username.lower() if isinstance(username, str) else ''
            user = self._users.get(username)
            valid = self._verify(password, user['password'] if user else self.dummy)
            if not user or not valid:
                self.failures.setdefault(bucket, []).append(now)
                return None
            # A valid account must not erase failures against other accounts.
            self.sessions = {key: value for key, value in self.sessions.items() if value['expires_at'] > now}
            token = secrets.token_urlsafe(32)
            session = {'token': token, 'csrf': secrets.token_urlsafe(32), 'username': username,
                       'role': user['role'], 'expires_at': now + self.session_ttl}
            self.sessions[token] = session
            return dict(session)

    def session(self, token):
        with self.lock:
            if not isinstance(token, str):
                return None
            session = self.sessions.get(token)
            if not session:
                return None
            if session['expires_at'] <= self.clock():
                self.sessions.pop(token, None)
                return None
            return dict(session)

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)

    def users(self):
        """Public account metadata only; caller enforces administrator access."""
        with self.lock:
            return [{'username': name, 'role': user['role']} for name, user in sorted(self._users.items())]

    def change_password(self, username, current, new):
        if not isinstance(new, str) or not 12 <= len(new) <= 1024:
            raise ValueError('Password must contain 12-1024 characters')
        with self.lock:
            user = self._users.get(username)
            if not user or not self._verify(current, user['password']):
                return False
            previous = user['password']
            user['password'] = self._hash(new)
            try:
                self._save()
            except Exception:
                user['password'] = previous
                raise
            self.sessions = {key: value for key, value in self.sessions.items() if value['username'] != username}
            if username == 'admin':
                (self.root / 'bootstrap-admin.txt').unlink(missing_ok=True)
            return True
