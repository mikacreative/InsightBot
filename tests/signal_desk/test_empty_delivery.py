"""结构性零稿 = fail-closed 的调度侧行为（PREFLIGHT-DESIGN-v0.1 §4.5／§5.4-2／§6-②／§7.3-④）。

判别式（已冻结）：``cards == []`` 且 非摘要证据数 == 0。
- 结构性零稿（零卡片 + 零非摘要证据）→ 独立终态 ``empty_delivery`` + 暂停定时计划 + 落盘升级记录。
- 合法零稿（有非摘要证据、只是卡片全不合格）→ 不暂停，仍走 awaiting_review／needs_revision。

本文件只验证调度侧的落点（终态／暂停／升级记录），不涉及外部通知外发。
"""
import copy
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="Install requirements-signal-desk.txt for the isolated Signal Desk runtime")

from insightbot.signal_desk import research_v2
from insightbot.signal_desk.workspace_v2 import EMPTY_DELIVERY, WorkspaceV2


ADMIN = {'username': 'admin', 'role': 'admin'}
ALICE = {'username': 'alice', 'role': 'editor'}
BEFORE = datetime.fromisoformat('2026-10-08T08:59:40+08:00')
DUE = datetime.fromisoformat('2026-10-08T09:00:00+08:00')
NEXT_DAY = datetime.fromisoformat('2026-10-09T09:00:00+08:00')
DAILY = {'frequency': 'daily', 'time': '09:00', 'window': 'last_7_days'}

# 非摘要证据（正文层）。判别式只关心 grades.summary_only，因此这里必须是非摘要等级。
NON_SUMMARY_EVIDENCE = [{'id': 'E1', 'title': '虚构办公个案', 'excerpt': '虚构摘录',
                         'url': 'https://example.org/fictional', 'source_grade': 'note_body'}]
CARD = {'title': '替换前核对兼容型号', 'observation': '该虚构个案提到核对型号。',
        'brand_reference': '供办公场景问题清单参考。', 'boundary': '单一个案不代表总体。',
        'question': '是否需要补充型号说明？', 'claim_type': 'signal',
        'evidence_ids': ['E1'], 'counter_evidence_ids': [], 'selection_reason': '相关个案'}


def empty_delivery_result():
    """零卡片的交付（编辑器合法产物：本轮没有达到门槛的判断）。"""
    return {'cards': [], 'candidates': [], 'lookback': None,
            'scope': '限定查询未取得可引用材料。', 'method_version': 'test', 'model_usage': []}


def card_delivery_result():
    return {'cards': [copy.deepcopy(CARD)], 'candidates': [], 'lookback': None,
            'scope': '虚构测试样本。', 'method_version': 'test', 'model_usage': []}


def collect_with(evidence):
    """本轮采集结果：证据集合由用例决定，状态随证据是否为空。"""
    return lambda *args, **kwargs: {'evidence': copy.deepcopy(evidence),
                                    'collection': {'status': 'complete' if evidence else 'empty'},
                                    'external_context': [], 'ledger': []}


def fake_editorial(monkeypatch, result):
    """替换 editorial_v2 为可控编辑器，把用例的注意力集中在终态分类上。"""
    import insightbot.signal_desk as package
    monkeypatch.setattr(package, 'editorial_v2', SimpleNamespace(
        edit=lambda *args, **kwargs: copy.deepcopy(result),
        validate_edition=lambda *args: [],
        render_markdown=lambda *args, **kwargs: '# Fictional'), raising=False)


@pytest.fixture
def scheduled(tmp_path):
    """一份已启用每日定时执行的品牌 workspace（时钟停在触发前）。"""
    (tmp_path / 'users.json').write_text(json.dumps(
        {'admin': {'role': 'admin'}, 'alice': {'role': 'editor'}, 'reviewer': {'role': 'editor'}}))
    ws = WorkspaceV2(tmp_path, start_worker=False, schedule_clock=lambda: BEFORE)
    brand = ws.post('/api/v2/brands', {'name': 'Fictional stationery',
        'members': {'admin': ['admin'], 'alice': ['researcher'], 'reviewer': ['reviewer']}}, ADMIN)
    plan = ws.post('/api/v2/plan', {'brand_id': brand['id'], 'request': '理解笔芯兼容如何影响办公选购',
        'keyword': '笔芯 兼容', 'start_date': '2026-09-01', 'end_date': '2026-09-07',
        'budget': {'queries': 2, 'samples': 8, 'body_reads': 2, 'model_calls': 2}}, ALICE)
    assert plan['ready']
    ws.post('/api/v2/schedule', {'brand_id': brand['id'], 'task_id': plan['task_id'],
        'plan_id': plan['id'], 'checksum': plan['checksum'], 'enabled': True, **DAILY}, ALICE)
    return ws, brand['id'], plan


def trigger_and_run(ws, brand_id):
    job = ws.tick_schedules(DUE)[0]
    return job, ws.process_job(brand_id, job['id'])


def schedule_of(ws, brand_id, plan):
    return ws.get('/api/v2/schedule', {'brand_id': brand_id, 'id': plan['task_id']}, ALICE)['schedule']


def test_structural_empty_delivery_pauses_schedule_and_records_escalation(scheduled, monkeypatch):
    """① 结构性零稿：fail-closed —— 独立终态 + 暂停调度 + 可审计升级记录。"""
    ws, brand_id, plan = scheduled
    monkeypatch.setattr(research_v2, 'collect', collect_with([]))  # 一条证据都没有
    fake_editorial(monkeypatch, empty_delivery_result())

    job, result = trigger_and_run(ws, brand_id)

    assert result['status'] == EMPTY_DELIVERY
    # 零稿交付没有被伪装成干净的 awaiting_review。
    assert ws.job(brand_id, job['id'], ALICE)['delivery']['cards'] == []

    schedule = schedule_of(ws, brand_id, plan)
    assert not schedule['enabled'] and schedule['status'] == 'paused'
    # 暂停原因必须说清是"零产出"，不能复用泛泛的失败文案。
    assert '未取得任何非摘要证据' in schedule['paused_reason']
    assert '未通过稿件校验' not in schedule['paused_reason']

    run = ws._read(brand_id, 'schedule_runs', job['id'])
    assert run['status'] == EMPTY_DELIVERY
    escalation = run['escalation']
    assert escalation['kind'] == EMPTY_DELIVERY
    assert escalation['reason'] == schedule['paused_reason']
    # 升级记录要能回答"哪一轮、为什么、什么时候"，且证据计数可与批准时的 preflight 对照。
    assert escalation['job_id'] == job['id'] and escalation['task_id'] == job['task_id']
    assert escalation['scheduled_for'] == job['scheduled_for'] and escalation['raised_at']
    assert escalation['summary_only_evidence'] == 0 and escalation['non_summary_evidence'] == 0

    # 暂停后不会再自动触发下一轮。
    assert ws.tick_schedules(NEXT_DAY) == []


def test_legal_empty_delivery_does_not_pause_schedule(scheduled, monkeypatch):
    """② 合法零稿：有非摘要证据、只是卡片全不合格 —— 记录而不暂停（PDD §7.2）。"""
    ws, brand_id, plan = scheduled
    monkeypatch.setattr(research_v2, 'collect', collect_with(NON_SUMMARY_EVIDENCE))
    fake_editorial(monkeypatch, empty_delivery_result())

    job, result = trigger_and_run(ws, brand_id)

    assert result['status'] == 'awaiting_review'
    schedule = schedule_of(ws, brand_id, plan)
    assert schedule['enabled'] and schedule['paused_reason'] is None
    run = ws._read(brand_id, 'schedule_runs', job['id'])
    assert run['status'] == 'awaiting_review' and 'escalation' not in run
    # 未被误判为零稿故障，定时计划照常继续。
    ws.tick_schedules(datetime.fromisoformat('2026-10-09T08:59:40+08:00'))
    assert ws.tick_schedules(NEXT_DAY)[0]['task_id'] == plan['task_id']


def test_normal_card_delivery_keeps_existing_behavior(scheduled, monkeypatch):
    """③ 正常有卡片：行为不变（不暂停、无升级记录）。"""
    ws, brand_id, plan = scheduled
    monkeypatch.setattr(research_v2, 'collect', collect_with(NON_SUMMARY_EVIDENCE))
    fake_editorial(monkeypatch, card_delivery_result())

    job, result = trigger_and_run(ws, brand_id)

    assert result['status'] == 'awaiting_review'
    assert schedule_of(ws, brand_id, plan)['enabled']
    run = ws._read(brand_id, 'schedule_runs', job['id'])
    assert run['status'] == 'awaiting_review' and 'escalation' not in run


def test_manual_structural_empty_delivery_is_terminal_without_a_schedule(tmp_path, monkeypatch):
    """④ 非定时（手动）运行下的结构性零稿。

    终态与定时运行一致：交付本身是结构性零稿，就标 empty_delivery，不伪装成 awaiting_review。
    差别只在处置：手动运行时没有定时计划可暂停，操作者就在现场，因此不写 schedule_runs
    升级记录（那个通道是给无人值守的送达底线用的）。失败闭合体现在终态本身。
    本条走真实的 editorial_v2（不经 fake）：采集为空时编辑器产出的是合法零稿交付。
    """
    ws = WorkspaceV2(tmp_path, start_worker=False)
    brand = ws.save_brand({'name': 'Fictional stationery'}, ADMIN, create=True)
    plan = ws.create_plan({'brand_id': brand['id'], 'request': '理解笔芯兼容如何影响办公选购',
                           'keyword': '笔芯 兼容'}, ADMIN)
    ws.confirm({'brand_id': brand['id'], 'plan_id': plan['id'], 'checksum': plan['checksum']}, ADMIN)
    job = ws.execute({'brand_id': brand['id'], 'plan_id': plan['id']}, ADMIN)
    monkeypatch.setattr(research_v2, 'collect', collect_with([]))

    assert ws.process_job(brand['id'], job['id'])['status'] == EMPTY_DELIVERY
    state = ws.job(brand['id'], job['id'], ADMIN)
    assert state['delivery']['cards'] == [] and state['errors'] == []
    assert ws._list(brand['id'], 'schedule_runs') == [] and not ws._list(brand['id'], 'schedules')
