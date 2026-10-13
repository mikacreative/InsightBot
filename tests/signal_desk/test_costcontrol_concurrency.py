"""Real local ledger contention, with no network calls or supplier credentials."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import multiprocessing
import os
from pathlib import Path
from threading import Barrier
import time

import pytest

from insightbot.signal_desk import costcontrol as c


def _attempt(operation, path, scope, reservation_id, code):
    if operation == 'authorize':
        result = c.authorize({c.DETAIL_V1: 1},
                             c.Envelope(scope, '2026-10', Decimal('0.15')),
                             channel='mcp' if code == 0 else 'rest', ledger=path)
        return result.allowed, result.reason
    try:
        row = c.settle(reservation_id, code=code, ledger=path)
        return True, row['code']
    except ValueError as error:
        if 'already settled' not in str(error):
            raise
        return False, 'already settled'


def _process_attempt(barrier, results, args):
    # Widen the read/write race, not the locking algorithm. Without the transaction
    # lock all contenders read the same old snapshot before any gets to append.
    original = c._read_ledger
    def delayed_read(path):
        rows = original(path)
        time.sleep(0.03)
        return rows
    c._read_ledger = delayed_read
    try:
        barrier.wait(timeout=10)
        results.put(('ok', _attempt(*args)))
    except BaseException as error:
        results.put(('error', repr(error)))


def _contend(kind, args, monkeypatch):
    if kind == 'thread':
        barrier = Barrier(len(args))
        original = c._read_ledger
        def delayed_read(path):
            rows = original(path)
            time.sleep(0.03)
            return rows
        monkeypatch.setattr(c, '_read_ledger', delayed_read)
        def call(value):
            barrier.wait(timeout=10)
            return _attempt(*value)
        with ThreadPoolExecutor(max_workers=len(args)) as pool:
            return list(pool.map(call, args, timeout=15))
    # spawn uses independent interpreters: a Python threading lock cannot pass this.
    ctx = multiprocessing.get_context('spawn')
    barrier, results = ctx.Barrier(len(args)), ctx.Queue()
    processes = [ctx.Process(target=_process_attempt, args=(barrier, results, value))
                 for value in args]
    try:
        for process in processes:
            process.start()
        received = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=5)
            assert process.exitcode == 0
        assert all(status == 'ok' for status, value in received), received
        return [value for status, value in received]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()


@pytest.mark.parametrize('kind', ['thread', 'process'])
def test_concurrent_authorization_cannot_overdraw_shared_envelope(kind, tmp_path, monkeypatch):
    path = tmp_path / 'spend.jsonl'
    args = [('authorize', path, 'fictional-brand', '', i % 2) for i in range(4)]
    outcomes = _contend(kind, args, monkeypatch)
    assert sum(allowed for allowed, _ in outcomes) == 1
    assert sum(reason == 'insufficient_budget' for _, reason in outcomes) == 3
    rows = c.load_ledger(path)
    assert len(rows) == 1 and rows[0]['kind'] == 'reserve'
    envelope = c.Envelope('fictional-brand', '2026-10', Decimal('0.15'))
    assert c.consumed(rows, envelope) == Decimal('0.15')
    assert c.remaining(rows, envelope) == 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert Path(str(path) + '.lock').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('kind', ['thread', 'process'])
def test_concurrent_duplicate_settlement_has_exactly_one_winner(kind, tmp_path, monkeypatch):
    path = tmp_path / 'spend.jsonl'
    envelope = c.Envelope('fictional-brand', '2026-10', Decimal('0.15'))
    reserved = c.authorize({c.DETAIL_V1: 1}, envelope, ledger=path)
    # Conflicting callbacks must not let a later failure replace a successful charge.
    args = [('settle', path, '', reserved.reservation_id, code) for code in (0, 301, 0, 301)]
    outcomes = _contend(kind, args, monkeypatch)
    winners = [code for won, code in outcomes if won]
    assert len(winners) == 1
    assert outcomes.count((False, 'already settled')) == 3
    rows = c.load_ledger(path)
    assert [row['kind'] for row in rows] == ['reserve', 'settle']
    assert rows[1]['code'] == winners[0]
    expected = Decimal('0.15') if winners[0] == 0 else Decimal('0')
    assert c.consumed(rows, envelope) == expected
    before = path.read_bytes()
    with pytest.raises(ValueError, match='already settled'):
        c.settle(reserved.reservation_id, code=301 if winners[0] == 0 else 0, ledger=path)
    assert path.read_bytes() == before


@pytest.mark.parametrize('kind', ['thread', 'process'])
def test_concurrent_brands_keep_separate_budgets(kind, tmp_path, monkeypatch):
    path = tmp_path / 'spend.jsonl'
    args = [('authorize', path, scope, '', 0)
            for scope in ('brand-a', 'brand-b', 'brand-a', 'brand-b')]
    outcomes = _contend(kind, args, monkeypatch)
    assert sum(allowed for allowed, _ in outcomes) == 2
    rows = c.load_ledger(path)
    assert sorted(row['scope'] for row in rows) == ['brand-a', 'brand-b']
    for scope in ('brand-a', 'brand-b'):
        assert c.remaining(rows, c.Envelope(scope, '2026-10', Decimal('0.15'))) == 0


def test_write_failure_releases_lock_without_creating_reservation(tmp_path, monkeypatch):
    path = tmp_path / 'spend.jsonl'
    envelope = c.Envelope('fictional-brand', '2026-10', Decimal('0.15'))
    with monkeypatch.context() as patch:
        def fail_write(*args):
            raise OSError('simulated write failure')
        patch.setattr(c, '_append_ledger', fail_write)
        with pytest.raises(OSError, match='write failure'):
            c.authorize({c.DETAIL_V1: 1}, envelope, ledger=path)
    assert c.load_ledger(path) == []
    assert c.authorize({c.DETAIL_V1: 1}, envelope, ledger=path).allowed


def _exit_holding_lock(path, ready):
    with c._ledger_lock(path):
        ready.set()
        os._exit(0)


def test_process_exit_releases_lock_and_keeps_outstanding_hold(tmp_path):
    path = tmp_path / 'spend.jsonl'
    envelope = c.Envelope('fictional-brand', '2026-10', Decimal('0.15'))
    reservation = c.authorize({c.DETAIL_V1: 1}, envelope, ledger=path)
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    process = ctx.Process(target=_exit_holding_lock, args=(path, ready))
    process.start()
    try:
        assert ready.wait(timeout=10)
        process.join(timeout=5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert not c.authorize({c.DETAIL_V1: 1}, envelope, ledger=path).allowed
    c.settle(reservation.reservation_id, code=301, ledger=path)
    assert c.authorize({c.DETAIL_V1: 1}, envelope, ledger=path).allowed


def test_symlink_alias_shares_the_ledger_lock(tmp_path, monkeypatch):
    path = tmp_path / 'spend.jsonl'
    path.touch(mode=0o600)
    alias = tmp_path / 'alias.jsonl'
    alias.symlink_to(path)
    args = [('authorize', target, 'fictional-brand', '', i % 2)
            for i, target in enumerate((path, alias, path, alias))]
    outcomes = _contend('thread', args, monkeypatch)
    assert sum(allowed for allowed, _ in outcomes) == 1
    assert len(c.load_ledger(path)) == 1
