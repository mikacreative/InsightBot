"""Approval, Shanghai month rollover and revocation against real isolated ledgers."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
import json
from threading import Barrier

import pytest

from insightbot.signal_desk import authorization as a, costcontrol as c, research_v2 as r, scheduling_v2
from insightbot.signal_desk.workspace_v2 import WorkspaceV2

OCT = datetime.fromisoformat('2026-10-31T23:59:40+08:00')
NOV = datetime.fromisoformat('2026-11-01T00:00:00+08:00')
ADMIN = {'username': 'admin', 'role': 'admin'}
ALICE = {'username': 'alice', 'role': 'editor'}
BOB = {'username': 'bob', 'role': 'editor'}
REVIEWER = {'username': 'reviewer', 'role': 'editor'}
DAILY = {'frequency': 'daily', 'time': '00:00', 'window': 'last_7_days'}


@pytest.fixture
def world(tmp_path, monkeypatch):
    clock = [OCT]
    monkeypatch.delenv(c.SPEND_LEDGER_ENV, raising=False)
    users = {u['username']: {'role': u['role']} for u in (ADMIN, ALICE, BOB, REVIEWER)}
    (tmp_path / 'users.json').write_text(json.dumps(users))
    ws = WorkspaceV2(tmp_path, start_worker=False, schedule_clock=lambda: clock[0])
    brand = ws.save_brand({'name': '虚构文具', 'members': {
        'admin': ['admin'], 'alice': ['researcher'], 'bob': ['researcher'], 'reviewer': ['reviewer']}}, ADMIN, create=True)
    policy = ws.authorization_policy({'brand_id': brand['id'], 'monthly_limit': '2', 'enabled': True,
        'allow_renew': True, 'renew_until': '2026-12-31', 'expected_version': 0}, ADMIN)
    plan = ws.create_plan({'brand_id': brand['id'], 'request': '理解笔芯兼容的选购疑问',
        'keyword': '笔芯兼容', 'start_date': '2026-10-01', 'end_date': '2026-10-07',
        'budget': {'body_reads': 1, 'comment_reads': 1}}, ALICE)
    return ws, brand['id'], plan, clock, policy


def approve(world, *, recurring=False, renew=False, until=None, request_id='confirm1'):
    ws, brand, plan, clock, policy = world
    values = {'brand_id': brand, 'plan_id': plan['id'], 'checksum': plan['checksum'],
              'funding': 'paid', 'approval_request_id': request_id,
              'auto_renew': renew, 'renew_until': until}
    if recurring:
        values.update(for_schedule=True, **DAILY)
    preview = ws.approval_preview(values, ALICE)
    values['approval_token'] = preview['approval_token']
    if recurring:
        values.update(task_id=plan['task_id'], enabled=True)
        ws.save_schedule(values, ALICE)
        return ws._read(brand, 'schedules', plan['task_id']), values
    return ws.confirm(values, ALICE), values


def reserve(world, plan, *, run='run1', request='detail1', at=None):
    ws, brand, original, clock, policy = world
    endpoint = c.COMMENT_V2 if request.startswith('comment') else c.DETAIL_V1
    run_id = plan['id'] if plan.get('scheduled_for') else 'plan_' + plan['id']
    return a.reserve(ws._spend_path(), plan['authorization'], plan, {endpoint: 1},
                     run_id=run_id, request_id=request, at=at or clock[0],
                     permission_check=lambda name: ws._approval_permission(brand, name))


def scheduled_plan(schedule, due):
    due = scheduling_v2.instant(due)
    value = scheduling_v2.frozen_run(schedule['plan_snapshot'], schedule['window'], due)
    run_id = 'schedule_' + a.digest({'confirmation': schedule['confirmation_id'], 'due': due.isoformat()})[:40]
    value.update(id=run_id, scheduled_for=due.isoformat(), scheduled_from_plan_id=schedule['plan_id'])
    return value


def rule_update(world, **changes):
    ws, brand, plan, clock, _ = world
    prior = a.policy(ws._spend_path(), brand)
    values = {'brand_id': brand, **{k: prior[k] for k in ('monthly_limit', 'enabled', 'allow_renew', 'renew_until')},
              'expected_version': prior['version'], **changes}
    return ws.authorization_policy(values, ADMIN)


def test_approval_is_fresh_idempotent_and_does_not_earmark_money(world):
    ws, brand, plan, clock, policy = world
    approved, payload = approve(world)
    assert ws.confirm(payload, ALICE) == approved
    rows = c.load_ledger(ws._spend_path())
    assert len([x for x in rows if x['kind'] == 'authorization_grant']) == 1
    assert not [x for x in rows if x['kind'] == 'reserve']
    assert approved['authorization']['approved_by'] == 'alice'
    assert ws.execute({'brand_id': brand, 'plan_id': plan['id']}, ALICE)['status'] == 'queued'


@pytest.mark.parametrize('change', ['policy', 'month', 'account', 'membership'])
def test_stale_approval_denied_after_live_state_changes(world, change):
    ws, brand, plan, clock, policy = world
    payload = {'brand_id': brand, 'plan_id': plan['id'], 'checksum': plan['checksum']}
    preview = ws.approval_preview(payload, ALICE)
    payload.update(funding='paid', approval_request_id='request1', approval_token=preview['approval_token'])
    if change == 'policy':
        rule_update(world, monthly_limit='1')
    elif change == 'month':
        clock[0] = NOV
    elif change == 'account':
        users = json.loads((ws.root / 'users.json').read_text());users['alice']['enabled'] = False
        (ws.root / 'users.json').write_text(json.dumps(users))
    else:
        ws.save_brand({'brand_id': brand, 'members': {'admin': ['admin']}}, ADMIN)
    with pytest.raises(PermissionError):
        ws.confirm(payload, ALICE)
    assert not [x for x in c.load_ledger(ws._spend_path()) if x['kind'] == 'authorization_grant']


def test_actual_paid_allowances_not_mode_recipe_are_checked_at_approval(world):
    ws, brand, plan, clock, policy = world
    preview = ws.approval_preview({'brand_id': brand, 'plan_id': plan['id'], 'checksum': plan['checksum']}, ALICE)
    assert Decimal(preview['maximum_cny']) == Decimal('0.30')
    rule_update(world, monthly_limit='0.29')
    with pytest.raises(PermissionError, match='余量不足'):
        approve(world)


def test_only_admin_can_change_policy_and_reviewer_cannot_approve(world):
    ws, brand, plan, clock, policy = world
    with pytest.raises(PermissionError):
        ws.authorization_policy({'brand_id': brand}, ALICE)
    with pytest.raises(PermissionError):
        ws.confirm({'brand_id': brand, 'plan_id': plan['id'], 'checksum': plan['checksum']}, REVIEWER)


def test_legacy_plan_cannot_execute_without_reconfirmation(world):
    ws, brand, plan, clock, policy = world
    plan['status'] = 'confirmed';ws._save(brand, 'plans', plan)
    with pytest.raises(PermissionError, match='旧方案'):
        ws.execute({'brand_id': brand, 'plan_id': plan['id']}, ALICE)
    approved, _ = approve(world)
    assert approved['authorization']['paid']


def test_no_renewal_pauses_schedule_at_shanghai_month_boundary(world):
    ws, brand, plan, clock, policy = world
    schedule, _ = approve(world, recurring=True)
    clock[0] = NOV
    assert ws.tick_schedules(at=NOV) == []
    saved = ws._read(brand, 'schedules', plan['task_id'])
    assert saved['status'] == 'paused' and not saved['enabled']
    assert not ws._list(brand, 'jobs')


def test_explicit_renewal_rolls_period_not_research_scope_and_keeps_old_charge(world):
    ws, brand, original, clock, policy = world
    schedule, _ = approve(world, recurring=True, renew=True, until='2026-11-30')
    before_plan = scheduled_plan(schedule, OCT)
    before = reserve(world, before_plan, run='old')
    clock[0] = NOV
    jobs = ws.tick_schedules(at=NOV)
    assert len(jobs) == 1
    run_plan = ws._read(brand, 'plans', jobs[0]['plan_id'])
    assert run_plan['end_date'] == '2026-11-01'
    assert run_plan['budget'] == original['budget']
    first = reserve(world, run_plan, run=jobs[0]['id'])
    # Second run in same month shares brand money and only one renewal event.
    next_plan = scheduled_plan(schedule, NOV + timedelta(days=1))
    second = reserve(world, next_plan, at=NOV + timedelta(days=1))
    rows = c.load_ledger(ws._spend_path())
    assert len([x for x in rows if x['kind'] == 'authorization_period']) == 1
    c.settle(before.reservation_id, code=0, ledger=ws._spend_path())
    rows = c.load_ledger(ws._spend_path())
    assert next(x for x in rows if x.get('reservation_id') == before.reservation_id and x['kind'] == 'settle')['period'] == '2026-10'
    assert {x['period'] for x in rows if x.get('reservation_id') in (first.reservation_id, second.reservation_id)} == {'2026-11'}


@pytest.mark.parametrize('at,period', [('2026-10-31T15:59:59+00:00','2026-10'),
                                      ('2026-10-31T16:00:00+00:00','2026-11')])
def test_month_uses_shanghai_not_utc_calendar(world, at, period):
    ws, _, _, clock, _ = world
    schedule, _ = approve(world, recurring=True, renew=True, until='2026-11-30')
    decision = reserve(world, scheduled_plan(schedule, datetime.fromisoformat(at)), at=datetime.fromisoformat(at))
    row = next(x for x in c.load_ledger(ws._spend_path()) if x.get('reservation_id') == decision.reservation_id)
    assert row['period'] == period


def test_renewal_requires_admin_permission_and_explicit_valid_deadline(world):
    with pytest.raises(PermissionError):
        approve(world, recurring=True, renew=True, until='2027-01-01')
    with pytest.raises(ValueError):
        approve(world, recurring=True, renew=True)
    rule_update(world, allow_renew=False)
    with pytest.raises(PermissionError):
        approve(world, recurring=True, renew=True, until='2026-11-30')


def test_expired_deadline_and_rollback_cannot_issue_a_new_period(world):
    ws, brand, plan, clock, policy = world
    schedule, _ = approve(world, recurring=True, renew=True, until='2026-11-01')
    with pytest.raises(c.BudgetDenied):
        reserve(world, schedule['plan_snapshot'], at=NOV + timedelta(days=1))


def test_cross_month_in_same_run_needs_renewal_but_old_hold_can_settle(world):
    ws, brand, plan, clock, policy = world
    approved, _ = approve(world)
    before = reserve(world, approved)
    with pytest.raises(c.BudgetDenied, match='到期'):
        reserve(world, approved, request='comment1', at=NOV)
    c.settle(before.reservation_id, code=0, ledger=ws._spend_path())
    assert c.load_ledger(ws._spend_path())[-1]['period'] == '2026-10'


def test_revoke_blocks_new_reservations_but_allows_old_settlement(world):
    ws, brand, plan, clock, policy = world
    approved, _ = approve(world)
    before = reserve(world, approved)
    payload = {'brand_id': brand, 'plan_id': plan['id']}
    with pytest.raises(PermissionError):
        ws.revoke_authorization(payload, BOB)
    ws.revoke_authorization(payload, ALICE)
    ws.revoke_authorization(payload, ALICE)  # idempotent revoke
    with pytest.raises(c.BudgetDenied, match='撤销'):
        reserve(world, approved, request='next', run='next')
    c.settle(before.reservation_id, code=0, ledger=ws._spend_path())
    assert c.load_ledger(ws._spend_path())[-1]['kind'] == 'settle'


def test_lowering_cap_does_not_refund_holds_or_increase_old_grant(world):
    ws, brand, plan, clock, policy = world
    approved, _ = approve(world)
    before = reserve(world, approved)
    rule_update(world, monthly_limit='0.10')
    with pytest.raises(c.BudgetDenied, match='额度不足'):
        reserve(world, approved, run='next', request='comment-next')
    assert c.load_ledger(ws._spend_path())[-1]['kind'] == 'authorization_policy'
    assert c.remaining(c.load_ledger(ws._spend_path()), c.Envelope(brand,'2026-10',Decimal('0.10'))) == Decimal('-0.05')
    rule_update(world, monthly_limit='100')
    assert a.check(ws._spend_path(), approved['authorization'], approved, at=clock[0]).limit_cny == Decimal('2')


def test_disabling_then_reenabling_does_not_resurrect_grant_or_schedule(world):
    ws, brand, plan, clock, policy = world
    schedule, payload = approve(world, recurring=True, renew=True, until='2026-11-30')
    rule_update(world, enabled=False)
    rule_update(world, enabled=True)
    with pytest.raises(c.BudgetDenied, match='撤销'):
        reserve(world, schedule['plan_snapshot'])
    assert ws.tick_schedules(at=clock[0]) == []
    assert not ws._read(brand,'schedules',plan['task_id'])['enabled']


def test_ledger_switch_and_deleted_ledger_fail_closed(world, tmp_path):
    ws, brand, plan, clock, policy = world
    approved, _ = approve(world)
    with pytest.raises(c.BudgetDenied, match='路径'):
        a.reserve(tmp_path/'new.jsonl', approved['authorization'], approved, {c.DETAIL_V1:1},run_id='r',request_id='x',at=clock[0])
    ws._spend_path().unlink()
    with pytest.raises(c.BudgetDenied, match='身份'):
        reserve(world, approved)


def test_approved_intent_cannot_be_modified_to_expand_scope(world):
    approved, _ = approve(world)
    changed = copy.deepcopy(approved);changed['budget']['body_reads'] = 6
    with pytest.raises(c.BudgetDenied, match='范围'):
        reserve(world, changed)


def test_conflicting_confirmation_ids_cannot_replace_grant(world):
    ws, brand, plan, clock, policy = world
    approved, payload = approve(world)
    changed = copy.deepcopy(plan);changed['question'] = '另一个问题'
    fresh = a.preview(ws._spend_path(), changed, at=clock[0])
    with pytest.raises(PermissionError, match='确认编号'):
        a.issue(ws._spend_path(), changed, actor='alice', confirmation_id=payload['approval_request_id'],
                approval_token=fresh['approval_token'], at=clock[0])


def test_confirmation_save_interrupted_recovers_same_ledger_grant(world, monkeypatch):
    ws, brand, plan, clock, policy = world
    preview = ws.approval_preview({'brand_id':brand,'plan_id':plan['id'],'checksum':plan['checksum']},ALICE)
    payload={'brand_id':brand,'plan_id':plan['id'],'checksum':plan['checksum'],'funding':'paid',
             'approval_token':preview['approval_token'],'approval_request_id':'recovery'}
    original = ws._save
    def fail_save(brand_id,kind,value):
        if kind == 'plans': raise OSError('disk full')
        return original(brand_id,kind,value)
    with monkeypatch.context() as patch:
        patch.setattr(ws,'_save',fail_save)
        with pytest.raises(OSError): ws.confirm(payload,ALICE)
    with pytest.raises(ValueError, match='确认'):
        ws.execute({'brand_id':brand,'plan_id':plan['id']},ALICE)
    recovered=ws.confirm(payload,ALICE)
    assert recovered['authorization']['paid']
    assert len([x for x in c.load_ledger(ws._spend_path()) if x['kind']=='authorization_grant']) == 1


def test_two_concurrent_approvals_do_not_duplicate_money(world):
    ws, brand, plan, clock, policy = world
    approved, payload=approve(world)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _: ws.confirm(payload,ALICE),range(2)))
    assert results[0]['authorization']==results[1]['authorization']
    assert not [x for x in c.load_ledger(ws._spend_path()) if x['kind']=='reserve']


def test_revoke_racing_reservation_has_only_the_two_legal_orderings(world):
    ws,brand,plan,clock,policy=world
    approved,_=approve(world)
    barrier=Barrier(2)
    def do_reserve():
        barrier.wait()
        try:return reserve(world,approved)
        except c.BudgetDenied:return None
    def do_revoke():
        barrier.wait()
        return ws.revoke_authorization({'brand_id':brand,'plan_id':plan['id']},ALICE)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(do_reserve);second=pool.submit(do_revoke)
        result=first.result(timeout=10);second.result(timeout=10)
    rows=c.load_ledger(ws._spend_path())
    events=[x['kind'] for x in rows if x['kind'] in ('reserve','authorization_revoke')]
    assert events in (['authorization_revoke'],['reserve','authorization_revoke'])
    if result:c.settle(result.reservation_id,code=0,ledger=ws._spend_path())
    with pytest.raises(c.BudgetDenied):reserve(world,approved,run='after')


def test_revoke_during_body_call_blocks_comments_and_still_settles_body(world):
    from test_spend_gate import PaidReader, FreeReader, collected, draft
    ws, brand, original, clock, policy = world
    approved, _ = approve(world)
    class Reader(PaidReader):
        def detail(self, url):
            ws.revoke_authorization({'brand_id': brand, 'plan_id': approved['id']}, ALICE)
            return super().detail(url)
        def comments(self, note_id):
            raise AssertionError('A revoked grant must not issue a new comment call')
    reader = Reader()
    run_dir = ws.root / ('plan_' + approved['id'])
    result = r.enrich(approved, collected(), draft(), run_dir, adapter=FreeReader(), body_adapter=reader,
        spend_ledger=ws._spend_path(), authorization_clock=lambda: clock[0],
        permission_check=lambda name: ws._approval_permission(brand, name))
    assert len(reader.urls) == 1
    rows = c.load_ledger(ws._spend_path())
    assert len([x for x in rows if x['kind'] == 'reserve']) == 1
    assert [x['code'] for x in rows if x['kind'] == 'settle'] == [0]
    assert any(x.get('reason') == 'budget_denied' for x in result['enrichment']['outcomes'])


def test_reconfirmation_after_revocation_requires_a_new_explicit_confirmation(world):
    ws, brand, original, clock, policy = world
    approved, payload = approve(world)
    ws.revoke_authorization({'brand_id': brand, 'plan_id': approved['id']}, ALICE)
    with pytest.raises(PermissionError):
        ws.confirm(payload, ALICE)
    world = (ws, brand, ws._read(brand, 'plans', original['id']), clock, policy)
    replacement, _ = approve(world, request_id='new-consent')
    assert replacement['authorization']['grant_id'] != approved['authorization']['grant_id']
    assert reserve(world, replacement).allowed


def _reserve_in_process(barrier, results, path, plan, at):
    barrier.wait(timeout=10)
    try:
        result = a.reserve(path, plan['authorization'], plan, {c.DETAIL_V1: 1},
            run_id='plan_' + plan['id'], request_id='detail1', at=at)
        results.put(result.allowed)
    except c.BudgetDenied:
        results.put(False)


def test_independent_grants_compete_for_same_month_budget_across_processes(world):
    import multiprocessing
    ws, brand, original, clock, policy = world
    first, _ = approve(world)
    second_plan = ws.create_plan({'brand_id': brand, 'request': '理解虚构文具的型号标注',
        'keyword': '文具型号', 'budget': {'body_reads': 1}}, ALICE)
    second, _ = approve((ws, brand, second_plan, clock, policy), request_id='second-plan')
    rule_update(world, monthly_limit='0.15')
    ctx = multiprocessing.get_context('spawn')
    barrier, results = ctx.Barrier(2), ctx.Queue()
    processes = [ctx.Process(target=_reserve_in_process,
        args=(barrier, results, ws._spend_path(), plan, clock[0])) for plan in (first, second)]
    try:
        for process in processes: process.start()
        outcomes = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=5)
            assert process.exitcode == 0
        assert sorted(outcomes) == [False, True]
        rows = c.load_ledger(ws._spend_path())
        assert len([x for x in rows if x['kind'] == 'reserve']) == 1
    finally:
        for process in processes:
            if process.is_alive(): process.terminate();process.join(timeout=5)
        results.close();results.join_thread()


def test_clock_rollback_and_run_identity_cannot_reuse_a_grant(world):
    approved, _ = approve(world)
    with pytest.raises(c.BudgetDenied, match='时钟'):
        reserve(world, approved, at=OCT - timedelta(seconds=1))
    ws, _, _, clock, _ = world
    with pytest.raises(c.BudgetDenied, match='运行'):
        a.reserve(ws._spend_path(), approved['authorization'], approved, {c.DETAIL_V1:1},
                  run_id='unrelated-run', request_id='x', at=clock[0])


def test_restart_preserves_live_renewal_without_replaying_missed_run(world):
    ws, brand, plan, clock, policy = world
    schedule, _ = approve(world, recurring=True, renew=True, until='2026-11-30')
    clock[0] = NOV + timedelta(seconds=20)
    restarted = WorkspaceV2(ws.root, start_worker=False, schedule_clock=lambda: clock[0])
    saved = restarted._read(brand, 'schedules', plan['task_id'])
    assert saved['enabled']
    assert scheduling_v2.instant(saved['next_run_at']) > clock[0]
    assert not restarted._list(brand, 'jobs')


@pytest.mark.parametrize('change', ['account', 'membership'])
def test_live_permission_loss_blocks_paid_call_after_approval(world, change):
    ws, brand, plan, clock, policy = world
    approved, _ = approve(world)
    if change == 'account':
        users = json.loads((ws.root/'users.json').read_text());users['alice']['enabled'] = False
        (ws.root/'users.json').write_text(json.dumps(users))
    else:
        ws.save_brand({'brand_id':brand,'members':{'admin':['admin']}},ADMIN)
    with pytest.raises((c.BudgetDenied, PermissionError)):
        reserve(world, approved)
    assert not [x for x in c.load_ledger(ws._spend_path()) if x['kind']=='reserve']


def test_revoking_one_grant_does_not_block_another_brand_grant(world):
    ws, brand, original, clock, policy = world
    first, _ = approve(world)
    other = ws.save_brand({'name':'另一个虚构品牌','members':{'admin':['admin'],'alice':['researcher']}}, ADMIN,create=True)
    ws.authorization_policy({'brand_id':other['id'],'monthly_limit':'1','enabled':True,
        'allow_renew':False,'expected_version':0},ADMIN)
    second_plan=ws.create_plan({'brand_id':other['id'],'request':'理解虚构文具型号','keyword':'文具型号',
                               'budget':{'body_reads':1}},ALICE)
    other_world=(ws,other['id'],second_plan,clock,policy)
    second,_=approve(other_world,request_id='other-brand')
    ws.revoke_authorization({'brand_id':brand,'plan_id':first['id']},ALICE)
    assert reserve(other_world,second).allowed


def test_consumed_balance_changes_between_preview_and_confirm_are_rechecked(world):
    ws,brand,original,clock,policy=world
    preview=ws.approval_preview({'brand_id':brand,'plan_id':original['id'],'checksum':original['checksum']},ALICE)
    # Simulate another legitimate path's outstanding hold on this same monthly ledger.
    c.authorize({c.DETAIL_V1:12},c.Envelope(brand,'2026-10',Decimal('2')),ledger=ws._spend_path())
    with pytest.raises(PermissionError,match='余量不足'):
        ws.confirm({'brand_id':brand,'plan_id':original['id'],'checksum':original['checksum'],
            'funding':'paid','approval_token':preview['approval_token'],'approval_request_id':'stale-balance'},ALICE)
    assert not [x for x in c.load_ledger(ws._spend_path()) if x['kind']=='authorization_grant']
