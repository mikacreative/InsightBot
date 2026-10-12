import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="Install requirements-signal-desk.txt for the isolated Signal Desk runtime")

from insightbot.signal_desk import research_v2, scheduling_v2
from insightbot.signal_desk.workspace_v2 import WorkspaceV2


ADMIN = {'username': 'admin', 'role': 'admin'}
ALICE = {'username': 'alice', 'role': 'editor'}
REVIEWER = {'username': 'reviewer', 'role': 'editor'}
BEFORE = datetime.fromisoformat('2026-10-08T08:59:40+08:00')
DUE = datetime.fromisoformat('2026-10-08T09:00:00+08:00')
DAILY = {'frequency': 'daily', 'time': '09:00', 'window': 'last_7_days'}


@pytest.fixture
def fixture_workspace(tmp_path):
    # Fictional account metadata only: never read real runtime users or credentials.
    users = {'admin': {'role': 'admin'}, 'alice': {'role': 'editor'}, 'reviewer': {'role': 'editor'}}
    (tmp_path / 'users.json').write_text(json.dumps(users), encoding='utf-8')
    ws = WorkspaceV2(tmp_path, start_worker=False, schedule_clock=lambda: BEFORE)
    brand = ws.post('/api/v2/brands', {'name': 'Fictional stationery',
        'members': {'admin': ['admin'], 'alice': ['researcher'], 'reviewer': ['reviewer']}}, ADMIN)
    plan = ws.post('/api/v2/plan', {'brand_id': brand['id'], 'request': '理解笔芯兼容如何影响办公选购',
        'keyword': '笔芯 兼容', 'start_date': '2026-09-01', 'end_date': '2026-09-07',
        'budget': {'queries': 2, 'samples': 8, 'body_reads': 2, 'model_calls': 2}}, ALICE)
    assert plan['ready']
    return ws, brand['id'], plan


@pytest.fixture
def fictional_pipeline(monkeypatch):
    import insightbot.signal_desk as package
    calls = {'collect': [], 'edit': []}
    evidence = [{'id': 'E1', 'title': '虚构办公个案', 'excerpt': '替换笔芯前核对兼容型号',
                 'url': 'https://example.org/fictional', 'source_grade': 'full_text'}]
    delivery = {'cards': [{'title': '替换前核对兼容型号', 'observation': '该虚构个案提到核对型号。',
                 'brand_reference': '供办公场景问题清单参考。', 'boundary': '单一个案不代表总体。',
                 'question': '是否需要补充型号说明？', 'claim_type': 'signal',
                 'evidence_ids': ['E1'], 'counter_evidence_ids': [], 'selection_reason': '相关个案'}],
                 'lookback': [], 'scope': '虚构测试样本', 'candidates': []}

    def collect(plan, run_dir):
        calls['collect'].append(copy.deepcopy(plan))
        return {'evidence': copy.deepcopy(evidence), 'external_context': [],
                'collection': {'status': 'complete'}, 'coverage': {},
                'ledger': [{'source': 'fictional', 'operation': 'read', 'status': 'success'}]}

    def edit(plan, collected, previous_editions=None, **kwargs):
        calls['edit'].append(copy.deepcopy(plan))
        return copy.deepcopy(delivery)

    monkeypatch.setattr(research_v2, 'collect', collect)
    monkeypatch.setattr(package, 'editorial_v2', SimpleNamespace(edit=edit,
        validate_edition=lambda *args: [], render_markdown=lambda *args, **kwargs: '# Fictional'), raising=False)
    return calls


def enable(ws, brand_id, plan, **config):
    return ws.post('/api/v2/schedule', {'brand_id': brand_id, 'task_id': plan['task_id'],
        'plan_id': plan['id'], 'checksum': plan['checksum'], 'enabled': True, **(config or DAILY)}, ALICE)['schedule']


def saved(ws, brand_id, plan):
    return ws.get('/api/v2/schedule', {'brand_id': brand_id, 'id': plan['task_id']}, ALICE)


@pytest.mark.parametrize('instruction,expected', [
    ('每天上午9点', {'frequency': 'daily', 'time': '09:00', 'window': 'fixed'}),
    ('每周一9:00', {'frequency': 'weekly', 'weekday': 0, 'time': '09:00', 'window': 'fixed'}),
    ('每周一早上9点，看上周的讨论', {'frequency': 'weekly', 'weekday': 0, 'time': '09:00', 'window': 'previous_week'}),
    ('改成每周五下午3点', {'frequency': 'weekly', 'weekday': 4, 'time': '15:00', 'window': 'previous_week'}),
    ('每天上午9：00，研究本月的样本', {'frequency': 'daily', 'time': '09:00', 'window': 'this_month'}),
    ('2026年10月9日上午九点半执行一次', {'frequency': 'once', 'date': '2026-10-09', 'time': '09:30', 'window': 'fixed'}),
    ('明天晚上八点', {'frequency': 'once', 'date': '2026-10-09', 'time': '20:00', 'window': 'fixed'}),
])
def test_explicit_natural_times(instruction, expected):
    default_window = 'previous_week' if instruction.startswith('改成') else 'fixed'
    parsed = scheduling_v2.parse_instruction(instruction, BEFORE, default_window)
    assert all(parsed[key] == value for key, value in expected.items())


@pytest.mark.parametrize('instruction', ['有空就研究', '每小时一次', '每天上午十十点',
    '每天上午一二十点', '每天上午25点', '每周五上午9点并删除养老查询', '2026年2月30日上午9点'])
def test_ambiguous_or_invalid_natural_times_are_not_guessed(instruction):
    assert scheduling_v2.parse_instruction(instruction, BEFORE) is None


@pytest.mark.parametrize('bad', [
    {'frequency': 'hourly', 'time': '09:00'}, {'frequency': 'daily', 'time': '9:00'},
    {'frequency': 'once', 'time': '09:00', 'date': '20261009'},
    {'frequency': 'once', 'time': '09:00', 'date': '2026-02-30'},
    {'frequency': 'weekly', 'time': '09:00', 'weekday': True},
    {'frequency': 'weekly', 'time': '09:00', 'weekday': 7},
    {'frequency': 'daily', 'time': '09:00', 'window': 'all_time'},
    {'frequency': 'daily', 'time': '09:00', 'cron': '* * * * *'},
])
def test_configuration_is_bounded_and_explicit(bad):
    with pytest.raises(ValueError):
        scheduling_v2.configuration(bad)


def test_preview_is_dialogue_without_planning_or_execution(fixture_workspace, monkeypatch):
    ws, brand_id, plan = fixture_workspace
    monkeypatch.setattr(research_v2, 'create_plan', lambda *a, **kw: pytest.fail('No paid or template replan'))
    before = ws.conversations(brand_id, ALICE, plan['task_id'])['conversation']
    result = ws.post('/api/v2/schedule-preview', {'brand_id': brand_id, 'task_id': plan['task_id'],
        'instruction': '每周一早上9点，看上周的讨论'}, ALICE)
    assert result['schedule'] is None and result['proposal']['valid']
    assert result['proposal']['timezone'] == 'Asia/Shanghai'
    assert result['proposal']['next_run_at'] == '2026-10-12T09:00:00+08:00'
    detail = ws.conversations(brand_id, ALICE, plan['task_id'])
    assert detail['plan']['id'] == plan['id'] and detail['task']['request'] == plan['task']['request']
    assert detail['conversation'] == before + [
        {'role': 'user', 'content': result['proposal']['instruction']},
        {'role': 'assistant', 'content': result['proposal']['message']}]
    assert len(ws._list(brand_id, 'planning')) == 1 and ws.queue.empty()
    invalid = ws.post('/api/v2/schedule-preview', {'brand_id': brand_id, 'task_id': plan['task_id'],
        'instruction': '有空就研究'}, ALICE)
    assert not invalid['proposal']['valid'] and '具体时间' in invalid['proposal']['message']
    assert ws.conversations(brand_id, ALICE, plan['task_id'])['conversation'][-2]['content'] == '有空就研究'


def test_new_time_preview_pauses_old_schedule_and_keeps_chosen_window(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan, frequency='weekly', time='09:00', weekday=0, window='previous_week')
    result = ws.post('/api/v2/schedule-preview', {'brand_id': brand_id, 'task_id': plan['task_id'],
        'instruction': '改成每周五下午3点'}, ALICE)
    assert not result['schedule']['enabled'] and result['schedule']['status'] == 'paused'
    assert result['proposal']['window'] == 'previous_week' and result['proposal']['time'] == '15:00'
    assert '重新启用' in result['schedule']['paused_reason']
    assert ws.tick_schedules(DUE) == []
    explicit = ws.post('/api/v2/schedule-preview', {'brand_id': brand_id, 'task_id': plan['task_id'],
        'instruction': '每天上午9点，看本月'}, ALICE)
    assert explicit['proposal']['window'] == 'this_month'


def test_valid_candidate_checksum_binds_the_actual_configuration(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    proposal = ws.post('/api/v2/schedule-preview', {'brand_id': brand_id, 'task_id': plan['task_id'], **DAILY}, ALICE)['proposal']
    payload = {'brand_id': brand_id, 'task_id': plan['task_id'], 'plan_id': plan['id'],
        'checksum': plan['checksum'], 'proposal_checksum': proposal['checksum'], 'enabled': True, **DAILY}
    for alteration in ({'proposal_checksum': 'old'}, {'time': '10:00'}, {'window': 'fixed'}):
        with pytest.raises(ValueError):
            ws.post('/api/v2/schedule', {**payload, **alteration}, ALICE)
    assert saved(ws, brand_id, plan)['schedule'] is None
    schedule = ws.post('/api/v2/schedule', payload, ALICE)['schedule']
    assert schedule['enabled'] and 'plan_snapshot' not in schedule
    assert ws.queue.empty() and not ws._list(brand_id, 'jobs')


def test_once_in_the_past_never_enables(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    config = {'frequency': 'once', 'date': '2026-10-07', 'time': '09:00'}
    preview = ws.post('/api/v2/schedule-preview', {'brand_id': brand_id, 'task_id': plan['task_id'], **config}, ALICE)
    assert not preview['proposal']['valid'] and '过去' in preview['proposal']['message']
    with pytest.raises(ValueError):
        enable(ws, brand_id, plan, **config)
    assert saved(ws, brand_id, plan)['schedule'] is None


def test_trigger_once_durable_snapshot_and_original_task_link(fixture_workspace, fictional_pipeline):
    ws, brand_id, plan = fixture_workspace
    schedule = enable(ws, brand_id, plan)
    jobs = ws.tick_schedules(DUE)
    assert len(jobs) == 1 and ws.tick_schedules(DUE) == []
    job = jobs[0]
    assert job['task_id'] == plan['task_id'] and job['schedule_plan_id'] == plan['id']
    assert job['schedule_id'] == plan['task_id'] and job['scheduled_for'] == DUE.isoformat()
    derived = ws._read(brand_id, 'plans', job['plan_id'])
    assert derived['start_date'] == '2026-10-02' and derived['end_date'] == '2026-10-08'
    assert all(derived[key] == plan[key] for key in ('budget', 'source_config', 'keyword', 'task_type', 'question'))
    assert [q['keyword'] for q in derived['queries']] == [q['keyword'] for q in plan['queries']]
    assert ws._read(brand_id, 'plans', plan['id'])['start_date'] == '2026-09-01'
    run = ws._read(brand_id, 'schedule_runs', job['id'])
    assert run['status'] == 'queued' and run['confirmation_id'] == schedule['confirmation_id']
    assert (ws._directory(brand_id) / 'schedule-trigger-started' / (job['id'] + '.started')).is_file()
    assert ws.process_job(brand_id, job['id'])['status'] == 'awaiting_review'
    assert len(fictional_pipeline['collect']) == len(fictional_pipeline['edit']) == 1
    assert fictional_pipeline['collect'][0]['budget'] == plan['budget']
    summary = ws.conversations(brand_id, ALICE, plan['task_id'])
    assert summary['plan']['id'] == plan['id'] and summary['job_id'] == job['id']
    assert [t['content'] for t in summary['conversation'] if t['role'] == 'user'] == [
        plan['task']['request'], '在任务详情启用自动执行']
    filtered = ws.get('/api/v2/jobs', {'brand_id': brand_id, 'task_id': plan['task_id']}, ALICE)['jobs']
    assert [j['id'] for j in filtered] == [job['id']]
    state = ws.job(brand_id, job['id'], ALICE)
    reviewed = ws.post('/api/v2/review', {'brand_id': brand_id, 'job_id': job['id'],
        'checksum': state['revision_checksum'], 'decision': 'approve'}, REVIEWER)
    assert reviewed['status'] == 'approved'
    next_day = datetime.fromisoformat('2026-10-09T08:59:40+08:00')
    assert ws.tick_schedules(next_day) == []
    second = ws.tick_schedules(datetime.fromisoformat('2026-10-09T09:00:00+08:00'))[0]
    assert second['id'] != job['id']
    assert ws._read(brand_id, 'plans', second['plan_id'])['budget'] == plan['budget']


@pytest.mark.parametrize('window,dates', [
    ('last_7_days', ('2026-10-02', '2026-10-08')),
    ('last_30_days', ('2026-09-09', '2026-10-08')),
    ('this_month', ('2026-10-01', '2026-10-08')),
    ('previous_month', ('2026-09-01', '2026-09-30')),
    ('this_week', ('2026-10-05', '2026-10-08')),
    ('previous_week', ('2026-09-28', '2026-10-04')),
])
def test_rolling_dates_keep_equal_previous_windows_and_frozen_fields(window, dates):
    plan = {'start_date': '2026-08-01', 'end_date': '2026-08-07', 'budget': {'model_calls': 1},
            'sources': {'qiangua': True}, 'queries': [
                {'keyword': '虚构 兼容', 'purpose': 'focus', 'kind': 'focus'},
                {'keyword': '虚构 兼容', 'purpose': 'previous', 'kind': 'focus', 'period': 'previous'}]}
    derived = scheduling_v2.frozen_run(plan, window, DUE)
    assert (derived['start_date'], derived['end_date']) == dates
    assert derived['budget'] == plan['budget'] and derived['sources'] == plan['sources']
    current, previous = derived['queries']
    start, end = map(datetime.fromisoformat, dates)
    previous_start = datetime.fromisoformat(previous['start_date'])
    previous_end = datetime.fromisoformat(previous['end_date'])
    assert end - start == previous_end - previous_start and (start - previous_end).days == 1
    assert {k: v for k, v in previous.items() if k not in ('start_date', 'end_date')} == plan['queries'][1]
    assert scheduling_v2.frozen_run(plan, 'fixed', DUE) == plan


def test_sleep_and_restart_skip_stale_trigger(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    after_sleep = datetime.fromisoformat('2026-10-08T10:00:00+08:00')
    assert ws.tick_schedules(after_sleep) == [] and ws.queue.empty()
    assert saved(ws, brand_id, plan)['schedule']['next_run_at'] == '2026-10-09T09:00:00+08:00'
    # Simulate stored due time before an independent restart; neither path catches up.
    record = ws._read(brand_id, 'schedules', plan['task_id'])
    record['next_run_at'] = DUE.isoformat()
    ws._save(brand_id, 'schedules', record)
    restarted = WorkspaceV2(ws.root, start_worker=False, schedule_clock=lambda: after_sleep)
    assert restarted.queue.empty() and restarted.tick_schedules(after_sleep) == []
    assert saved(restarted, brand_id, plan)['schedule']['next_run_at'] == '2026-10-09T09:00:00+08:00'


def test_missed_once_is_paused_after_restart(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan, frequency='once', time='09:00', date='2026-10-08', window='fixed')
    restarted = WorkspaceV2(ws.root, start_worker=False,
        schedule_clock=lambda: datetime.fromisoformat('2026-10-08T10:00:00+08:00'))
    schedule = saved(restarted, brand_id, plan)['schedule']
    assert not schedule['enabled'] and '错过' in schedule['paused_reason'] and restarted.queue.empty()


def test_overlap_is_skipped_and_does_not_queue_another_run(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    ws.confirm({'brand_id': brand_id, 'plan_id': plan['id'], 'checksum': plan['checksum']}, ALICE)
    manual = ws.execute({'brand_id': brand_id, 'plan_id': plan['id']}, ALICE)
    assert ws.tick_schedules(DUE) == []
    assert len(ws._list(brand_id, 'jobs')) == 1 and ws._list(brand_id, 'jobs')[0]['id'] == manual['id']
    assert ws._list(brand_id, 'schedule_runs')[0]['status'] == 'skipped_overlap'
    assert '上一轮' in saved(ws, brand_id, plan)['schedule']['last_skip_reason']


@pytest.mark.parametrize('failure_at', ['schedule_runs', 'jobs'])
def test_interrupted_claim_never_replays_after_restart(fixture_workspace, monkeypatch, failure_at):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    write = ws._save

    def interrupted(brand, kind, value):
        if kind == failure_at:
            raise OSError('fictional write interruption')
        return write(brand, kind, value)

    monkeypatch.setattr(ws, '_save', interrupted)
    with pytest.raises(OSError):
        ws.tick_schedules(DUE)
    monkeypatch.setattr(ws, '_save', write)
    assert ws.queue.empty() and not ws._list(brand_id, 'jobs')
    restarted = WorkspaceV2(ws.root, start_worker=False, schedule_clock=lambda: DUE)
    schedule = saved(restarted, brand_id, plan)['schedule']
    assert not schedule['enabled'] and '不会重试' in schedule['paused_reason']
    assert restarted.tick_schedules(DUE) == [] and restarted.queue.empty()


def test_queued_restart_is_interrupted_and_pauses_recurring_schedule(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    job = ws.tick_schedules(DUE)[0]
    restarted = WorkspaceV2(ws.root, start_worker=False, schedule_clock=lambda: DUE)
    assert restarted._read(brand_id, 'jobs', job['id'])['status'] == 'interrupted'
    assert restarted._read(brand_id, 'schedule_runs', job['id'])['status'] == 'interrupted'
    assert not saved(restarted, brand_id, plan)['schedule']['enabled']
    assert restarted.process_job(brand_id, job['id'])['status'] == 'interrupted'


def test_final_commit_interruption_pauses_pending_job_on_next_tick(fixture_workspace, monkeypatch, fictional_pipeline):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    write = ws._save

    def interrupted(brand, kind, value):
        if kind == 'schedules':
            raise OSError('fictional final commit interruption')
        return write(brand, kind, value)

    monkeypatch.setattr(ws, '_save', interrupted)
    with pytest.raises(OSError):
        ws.tick_schedules(DUE)
    monkeypatch.setattr(ws, '_save', write)
    job = ws._list(brand_id, 'jobs')[0]
    assert job['status'] == 'queued' and ws.queue.empty()
    assert ws.tick_schedules(datetime.fromisoformat('2026-10-08T09:00:20+08:00')) == []
    assert not saved(ws, brand_id, plan)['schedule']['enabled']
    assert ws.process_job(brand_id, job['id'])['status'] == 'interrupted'
    assert not fictional_pipeline['collect'] and not fictional_pipeline['edit']


def test_once_run_can_complete_but_never_recurs(fixture_workspace, fictional_pipeline):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan, frequency='once', time='09:00', date='2026-10-08', window='fixed')
    job = ws.tick_schedules(DUE)[0]
    schedule = saved(ws, brand_id, plan)['schedule']
    assert not schedule['enabled'] and schedule['status'] == 'exhausted' and schedule['next_run_at'] is None
    assert ws.process_job(brand_id, job['id'])['status'] == 'awaiting_review'
    assert fictional_pipeline['collect'][0]['queries'] == plan['queries']
    assert ws.tick_schedules(datetime.fromisoformat('2026-10-09T09:00:00+08:00')) == []


def test_disable_after_enqueue_stops_before_provider_without_plan_fields(fixture_workspace, fictional_pipeline):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    job = ws.tick_schedules(DUE)[0]
    ws.save_schedule({'brand_id': brand_id, 'task_id': plan['task_id'], 'enabled': False}, ALICE)
    assert ws.process_job(brand_id, job['id'])['status'] == 'interrupted'
    assert not fictional_pipeline['collect'] and not fictional_pipeline['edit']


def test_manual_execute_after_scheduled_enqueue_shares_same_run(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    job = ws.tick_schedules(DUE)[0]
    result = ws.execute({'brand_id': brand_id, 'plan_id': plan['id']}, ALICE)
    assert result['id'] == job['id'] and len(ws._list(brand_id, 'jobs')) == 1
    revised = ws.create_plan({'brand_id': brand_id, 'task_id': plan['task_id'],
        'request': plan['task']['request'], 'keyword': '办公 笔芯 兼容'}, ALICE)
    assert ws.execute({'brand_id': brand_id, 'plan_id': plan['id']}, ALICE)['id'] == job['id']
    ws.confirm({'brand_id': brand_id, 'plan_id': revised['id'], 'checksum': revised['checksum']}, ALICE)
    with pytest.raises(ValueError, match='上一轮仍在执行'):
        ws.execute({'brand_id': brand_id, 'plan_id': revised['id']}, ALICE)
    assert len(ws._list(brand_id, 'jobs')) == 1


def test_stale_confirmed_tab_cannot_execute_after_new_plan(fixture_workspace):
    ws, brand_id, first = fixture_workspace
    ws.confirm({'brand_id': brand_id, 'plan_id': first['id'], 'checksum': first['checksum']}, ALICE)
    revised = ws.create_plan({'brand_id': brand_id, 'task_id': first['task_id'],
        'request': first['task']['request'], 'keyword': '纸张 兼容',
        'start_date': '2026-10-01', 'end_date': '2026-10-07'}, ALICE)
    assert revised['ready']
    for action in ('confirm', 'execute'):
        with pytest.raises(ValueError, match='最新方案'):
            ws.post('/api/v2/' + action, {'brand_id': brand_id, 'plan_id': first['id'],
                'checksum': first['checksum']}, ALICE)
    assert ws.queue.empty() and ws._list(brand_id, 'jobs') == []
    ws.confirm({'brand_id': brand_id, 'plan_id': revised['id'], 'checksum': revised['checksum']}, ALICE)
    assert ws.execute({'brand_id': brand_id, 'plan_id': revised['id']}, ALICE)['plan_id'] == revised['id']


@pytest.mark.parametrize('status', ['running', 'failed', 'interrupted'])
def test_pending_or_incomplete_update_blocks_old_confirm_and_new_execute(fixture_workspace, status):
    ws, brand_id, plan = fixture_workspace
    ws.confirm({'brand_id': brand_id, 'plan_id': plan['id'], 'checksum': plan['checksum']}, ALICE)
    ws._save(brand_id, 'planning', {'id': 'unfinished_update', 'brand_id': brand_id,
        'task_id': plan['task_id'], 'status': status,
        'created_at': (datetime.fromisoformat(plan['created_at']) + timedelta(microseconds=1)).isoformat()})
    for action in ('confirm', 'execute'):
        with pytest.raises(ValueError):
            ws.post('/api/v2/' + action, {'brand_id': brand_id, 'plan_id': plan['id'],
                'checksum': plan['checksum']}, ALICE)
    with pytest.raises(ValueError):
        enable(ws, brand_id, plan)
    assert ws.queue.empty() and ws._list(brand_id, 'jobs') == []
    old_operation = ws._read(brand_id, 'planning', 'unfinished_update')
    old_operation['status'] = 'interrupted'
    ws._save(brand_id, 'planning', old_operation)
    revised = ws.create_plan({'brand_id': brand_id, 'task_id': plan['task_id'],
        'request': plan['task']['request'], 'keyword': '办公 笔芯 兼容'}, ALICE)
    ws.confirm({'brand_id': brand_id, 'plan_id': revised['id'], 'checksum': revised['checksum']}, ALICE)
    assert ws.execute({'brand_id': brand_id, 'plan_id': revised['id']}, ALICE)['plan_id'] == revised['id']


def test_historical_job_remains_idempotent_after_new_dialogue(fixture_workspace):
    ws, brand_id, first = fixture_workspace
    ws.confirm({'brand_id': brand_id, 'plan_id': first['id'], 'checksum': first['checksum']}, ALICE)
    job = ws.execute({'brand_id': brand_id, 'plan_id': first['id']}, ALICE)
    job.update(status='interrupted', error='虚构中断，结果待核对')
    ws._save(brand_id, 'jobs', job)
    revised = ws.create_plan({'brand_id': brand_id, 'task_id': first['task_id'],
        'request': first['task']['request'], 'keyword': '纸张 兼容'}, ALICE)
    assert revised['id'] != first['id']
    count = ws.queue.qsize()
    response = ws.execute({'brand_id': brand_id, 'plan_id': first['id']}, ALICE)
    assert response == job and ws.queue.qsize() == count
    assert len(ws._list(brand_id, 'jobs')) == 1


def test_confirmation_events_survive_refresh_and_repeated_enable_is_idempotent(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    first = enable(ws, brand_id, plan)
    second = enable(ws, brand_id, plan)
    assert first['confirmation_id'] == second['confirmation_id']
    transcript = ws.conversations(brand_id, ALICE, plan['task_id'])['conversation']
    assert transcript[-2]['content'] == '在任务详情启用自动执行'
    assert '已启用' in transcript[-1]['content'] and '。。' not in transcript[-1]['content']
    assert len(ws._list(brand_id, 'dialogue_events')) == 1
    response = ws.save_schedule({'brand_id': brand_id, 'task_id': plan['task_id'], 'enabled': False}, ALICE)
    assert '已暂停' in response['message']
    transcript = ws.conversations(brand_id, ALICE, plan['task_id'])['conversation']
    assert transcript[-2]['content'] == '在任务详情暂停自动执行'
    assert '已暂停' in transcript[-1]['content']


def test_provider_failure_pauses_without_next_day_retry(fixture_workspace, monkeypatch):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    calls = []

    def failure(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('fictional-provider-token-must-not-leak')

    monkeypatch.setattr(research_v2, 'collect', failure)
    job = ws.tick_schedules(DUE)[0]
    assert ws.process_job(brand_id, job['id'])['status'] == 'failed'
    schedule = saved(ws, brand_id, plan)['schedule']
    assert not schedule['enabled'] and '来源采集未完成' in schedule['paused_reason']
    assert 'provider-token' not in json.dumps(schedule)
    ws.tick_schedules(datetime.fromisoformat('2026-10-09T08:59:40+08:00'))
    assert ws.tick_schedules(datetime.fromisoformat('2026-10-09T09:00:00+08:00')) == []
    ws.process_job(brand_id, job['id'])
    assert len(calls) == 1


def test_partial_unknown_source_keeps_review_but_pauses_schedule(fixture_workspace, fictional_pipeline, monkeypatch):
    ws, brand_id, plan = fixture_workspace
    collect = research_v2.collect

    def uncertain(*args, **kwargs):
        result = collect(*args, **kwargs)
        result['ledger'].append({'source': 'fictional', 'status': 'unknown'})
        return result

    monkeypatch.setattr(research_v2, 'collect', uncertain)
    enable(ws, brand_id, plan)
    job = ws.tick_schedules(DUE)[0]
    assert ws.process_job(brand_id, job['id'])['status'] == 'awaiting_review'
    assert not saved(ws, brand_id, plan)['schedule']['enabled']
    assert len(fictional_pipeline['collect']) == 1


@pytest.mark.parametrize('record_error', ['collection', 'rss', 'web'])
def test_partial_background_failure_pauses_next_cycle(fixture_workspace, fictional_pipeline, monkeypatch, record_error):
    ws, brand_id, plan = fixture_workspace
    collect = research_v2.collect

    def background_failure(*args, **kwargs):
        result = collect(*args, **kwargs)
        result['collection']['status'] = 'partial'
        if record_error == 'collection':
            result['collection']['errors'] = [{'source': 'web', 'message': '虚构背景来源失败'}]
        else:
            result['ledger'].append({'source': record_error, 'operation': 'background', 'items': 0, 'errors': 1})
        return result

    monkeypatch.setattr(research_v2, 'collect', background_failure)
    enable(ws, brand_id, plan)
    job = ws.tick_schedules(DUE)[0]
    assert ws.process_job(brand_id, job['id'])['status'] == 'awaiting_review'
    assert not saved(ws, brand_id, plan)['schedule']['enabled']
    ws.tick_schedules(datetime.fromisoformat('2026-10-09T08:59:40+08:00'))
    assert ws.tick_schedules(datetime.fromisoformat('2026-10-09T09:00:00+08:00')) == []
    assert len(fictional_pipeline['collect']) == 1


@pytest.mark.parametrize('change', ['disabled_account', 'deleted_account', 'research_role'])
def test_revoked_owner_or_research_permission_pauses(fixture_workspace, change):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    if change == 'research_role':
        ws.save_brand({'brand_id': brand_id, 'members': {'admin': ['admin'], 'alice': ['reviewer']}}, ADMIN)
    else:
        path = ws.root / 'users.json'
        users = json.loads(path.read_text())
        if change == 'disabled_account':
            users['alice']['enabled'] = False
        else:
            del users['alice']
        path.write_text(json.dumps(users))
    assert ws.tick_schedules(DUE) == []
    assert not ws._read(brand_id, 'schedules', plan['task_id'])['enabled']
    assert not ws._list(brand_id, 'jobs')


def test_role_revocation_after_enqueue_stops_before_provider(fixture_workspace, fictional_pipeline):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    job = ws.tick_schedules(DUE)[0]
    ws.save_brand({'brand_id': brand_id, 'members': {'admin': ['admin'], 'alice': ['reviewer']}}, ADMIN)
    assert ws.process_job(brand_id, job['id'])['status'] == 'interrupted'
    assert not fictional_pipeline['collect'] and not fictional_pipeline['edit']


def test_role_revocation_between_source_and_model_stops_new_paid_stage(fixture_workspace, fictional_pipeline, monkeypatch):
    ws, brand_id, plan = fixture_workspace
    collect = research_v2.collect

    def revoke(*args, **kwargs):
        result = collect(*args, **kwargs)
        ws.save_brand({'brand_id': brand_id, 'members': {'admin': ['admin'], 'alice': ['reviewer']}}, ADMIN)
        return result

    monkeypatch.setattr(research_v2, 'collect', revoke)
    enable(ws, brand_id, plan)
    job = ws.tick_schedules(DUE)[0]
    assert ws.process_job(brand_id, job['id'])['status'] == 'interrupted'
    assert len(fictional_pipeline['collect']) == 1 and not fictional_pipeline['edit']
    assert (ws._directory(brand_id) / 'runs' / job['id'] / 'collection.json').is_file()


def test_new_dialogue_draft_pauses_old_and_disable_needs_no_valid_plan(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    draft = ws.create_plan({'brand_id': brand_id, 'task_id': plan['task_id'],
        'request': plan['task']['request'], 'keyword': ''}, ALICE)
    assert not draft['ready'] and not saved(ws, brand_id, plan)['schedule']['enabled']
    disabled = ws.post('/api/v2/schedule', {'brand_id': brand_id, 'task_id': plan['task_id'], 'enabled': False}, ALICE)
    assert not disabled['schedule']['enabled']
    with pytest.raises(ValueError):
        enable(ws, brand_id, plan)
    with pytest.raises(ValueError):
        enable(ws, brand_id, draft)


def test_pause_command_is_safe_and_retained_in_task_dialogue(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    enable(ws, brand_id, plan)
    result = ws.post('/api/v2/schedule-preview', {'brand_id': brand_id, 'task_id': plan['task_id'],
        'instruction': '暂停自动执行'}, ALICE)
    assert result['proposal']['action'] == 'pause' and not result['schedule']['enabled']
    transcript = ws.conversations(brand_id, ALICE, plan['task_id'])['conversation']
    assert transcript[-2]['content'] == '暂停自动执行' and '已暂停' in transcript[-1]['content']


def test_schedule_dialogue_interleaves_research_without_duplicate_history(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    ws.schedule_preview({'brand_id': brand_id, 'task_id': plan['task_id'], 'instruction': '每天上午9点'}, ALICE)
    transcript = ws.conversations(brand_id, ALICE, plan['task_id'])['conversation']
    transcript.append({'role': 'user', 'content': '只看办公替换场景。'})
    revised = ws.create_plan({'brand_id': brand_id, 'task_id': plan['task_id'],
        'request': plan['task']['request'], 'keyword': '办公 笔芯 兼容', 'conversation': transcript[-8:]}, ALICE)
    detail = ws.conversations(brand_id, ALICE, plan['task_id'])
    assert detail['plan']['id'] == revised['id']
    assert detail['conversation'][:-1] == transcript
    assert [t['content'] for t in detail['conversation'] if t['role'] == 'user'] == [
        plan['task']['request'], '每天上午9点', '只看办公替换场景。']


def test_task_title_and_schedule_routes_preserve_brand_boundaries(fixture_workspace):
    ws, brand_id, plan = fixture_workspace
    renamed = ws.post('/api/v2/task-title', {'brand_id': brand_id, 'task_id': plan['task_id'],
        'title': '办公笔芯兼容观察'}, ALICE)
    assert renamed['request'] == plan['task']['request']
    assert ws.conversations(brand_id, ALICE)['conversations'][0]['title'] == '办公笔芯兼容观察'
    with pytest.raises(ValueError):
        ws.task_title({'brand_id': brand_id, 'task_id': plan['task_id'], 'title': '字' * 151}, ALICE)
    other = ws.save_brand({'name': 'Another fictional brand', 'members': {'admin': ['admin'], 'alice': ['researcher']}}, ADMIN, create=True)
    for route, query in [('schedule', {'id': plan['task_id']}), ('jobs', {'task_id': plan['task_id']})]:
        with pytest.raises(ValueError):
            ws.get('/api/v2/' + route, {'brand_id': other['id'], **query}, ALICE)
    for route, extra in [('schedule-preview', {'instruction': '每天上午9点'}),
                         ('schedule', {'enabled': False}), ('task-title', {'title': '越权任务'})]:
        with pytest.raises(ValueError):
            ws.post('/api/v2/' + route, {'brand_id': other['id'], 'task_id': plan['task_id'], **extra}, ALICE)
        with pytest.raises(PermissionError):
            ws.post('/api/v2/' + route, {'brand_id': brand_id, 'task_id': plan['task_id'], **extra}, REVIEWER)


def test_scheduler_only_starts_with_worker_and_waits_before_tick(tmp_path, monkeypatch):
    import insightbot.signal_desk.workspace_v2 as module
    started = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self.kwargs)

    monkeypatch.setattr(module.threading, 'Thread', FakeThread)
    WorkspaceV2(tmp_path, start_worker=False, schedule_clock=lambda: BEFORE)
    assert started == []
    ws = WorkspaceV2(tmp_path, start_worker=True, schedule_clock=lambda: BEFORE)
    assert [t['name'] for t in started] == ['signal-desk-v2', 'signal-desk-v2-scheduler']
    waits = []
    ws._scheduler_stop = SimpleNamespace(wait=lambda seconds: waits.append(seconds) or True)
    monkeypatch.setattr(ws, 'tick_schedules', lambda *a: pytest.fail('Must wait before first tick'))
    ws._scheduler()
    assert waits == [30]
