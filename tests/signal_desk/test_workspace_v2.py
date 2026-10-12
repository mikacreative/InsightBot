import copy
import json
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="Install requirements-signal-desk.txt for the isolated Signal Desk runtime")

from insightbot.signal_desk.workspace_v2 import WorkspaceV2, DEFAULT_DELIVERY
from insightbot.signal_desk import research_v2

ADMIN = {'username': 'admin', 'role': 'admin'}
ALICE = {'username': 'alice', 'role': 'editor'}
BOB = {'username': 'bob', 'role': 'editor'}
REVIEWER = {'username': 'reviewer', 'role': 'editor'}


def brand(ws, name='A', members=None):
    return ws.post('/api/v2/brands', {'name': name, 'audience': '生活场景样本',
                   'members': members or {'admin': ['admin'], 'alice': ['researcher'],
                                         'reviewer': ['reviewer']}}, ADMIN)


def issue(ws, brand_id):
    return ws.post('/api/v2/issues', {'brand_id': brand_id, 'title': '照护与生活',
                   'question': '家庭照护如何影响个人安排？'}, ALICE)


def plan(ws, brand_id, **extra):
    return ws.post('/api/v2/plan', {'brand_id': brand_id, 'request': '理解照护安排',
                   'keyword': '家庭照护', **extra}, ALICE)


def enqueue(ws, brand_id, **extra):
    p = plan(ws, brand_id, **extra)
    ws.post('/api/v2/confirm', {'brand_id': brand_id, 'plan_id': p['id'], 'checksum': p['checksum']}, ALICE)
    return ws.post('/api/v2/execute', {'brand_id': brand_id, 'plan_id': p['id']}, ALICE)


@pytest.fixture
def pipeline(monkeypatch):
    import insightbot.signal_desk as package
    calls = {'collect': 0, 'edit': 0, 'previous': []}
    evidence = [{'id': 'E1', 'title': '某位作者的照护自述', 'excerpt': '家人分工改变生活安排',
                 'url': 'https://example.org/evidence', 'source_grade': 'full_text'}]
    delivery = {'cards': [{'title': '个案里家庭分工影响生活安排', 'observation': '该作者的自述显示家人分工带来时间约束。',
                 'brand_reference': '补充照护沟通里的家庭视角。', 'boundary': '单一个案不代表总体。',
                 'question': '现有问题清单是否覆盖家人分工？', 'claim_type': 'signal',
                 'evidence_ids': ['E1'], 'counter_evidence_ids': [], 'selection_reason': '相关个案'}],
                 'lookback': [], 'scope': '本次检索样本，仅作个案参考。', 'candidates': []}

    def collect(plan, run_dir):
        calls['collect'] += 1
        return {'evidence': copy.deepcopy(evidence), 'external_context': [],
                'collection': {'status': 'complete'}, 'coverage': {}, 'ledger': []}

    def edit(plan, collected, previous_editions=None, **kwargs):
        calls['edit'] += 1
        calls['previous'].append(copy.deepcopy(previous_editions))
        return copy.deepcopy(delivery)

    def validate(result, sources, profile=None, previous=None):
        errors = []
        if len(result.get('cards', [])) > 3:
            errors.append('最多3条精选')
        for card in result.get('cards', []):
            if not set(card.get('evidence_ids', [])) <= {e['id'] for e in sources}:
                errors.append('证据引用无效')
            if len(card.get('title', '')) > 26:
                errors.append('标题超限')
        return errors

    monkeypatch.setattr(research_v2, 'collect', collect)
    fake = SimpleNamespace(edit=edit, validate_edition=validate,
           render_markdown=lambda edition, sources, brand_name='': '# ' + brand_name + '\n' + edition['cards'][0]['title'])
    monkeypatch.setattr(package, 'editorial_v2', fake, raising=False)
    return calls


def test_brands_default_deny_and_no_homepage_private_content(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    b = brand(ws, 'B', {'admin': ['admin'], 'bob': ['researcher', 'reviewer']})
    assert [x['id'] for x in ws.get('/api/v2/brands', {}, ALICE)['brands']] == [a['id']]
    assert 'audience' not in ws.get('/api/v2/brands', {}, ALICE)['brands'][0]
    assert 'members' not in ws.get('/api/v2/brand', {'brand_id': a['id']}, ALICE)
    for route in ('brand', 'jobs', 'editions', 'feedback', 'config', 'issues', 'tasks', 'artifact', 'job', 'plan', 'conversations', 'conversation'):
        with pytest.raises(PermissionError):
            ws.get('/api/v2/' + route, {'brand_id': b['id'], 'id': 'guessed'}, ALICE)
    with pytest.raises(PermissionError):
        ws.post('/api/v2/brands', {'name': 'Unauthorized'}, ALICE)
    with pytest.raises(PermissionError):
        ws.post('/api/v2/brand', {'brand_id': a['id'], 'members': {'alice': ['admin']}}, ALICE)


def test_guessed_crossbrand_resource_and_issue_never_resolves(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    b = brand(ws, 'B')
    p = plan(ws, a['id'])
    i = issue(ws, a['id'])
    with pytest.raises(ValueError):
        ws.get('/api/v2/plan', {'brand_id': b['id'], 'id': p['id']}, ALICE)
    with pytest.raises(ValueError):
        plan(ws, b['id'], issue_id=i['id'])
    with pytest.raises(ValueError):
        ws.get('/api/v2/jobs', {'brand_id': '../outside'}, ALICE)


def test_frozen_brand_and_budget_confirmation_idempotency(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    p = plan(ws, a['id'], budget={'queries': 2, 'samples': 10}, request_id='request1')
    assert plan(ws, a['id'], budget={'queries': 2, 'samples': 10}, request_id='request1')['id'] == p['id']
    ws.post('/api/v2/brand', {'brand_id': a['id'], 'audience': 'Updated audience'}, ADMIN)
    assert p['brand_snapshot']['audience'] != 'Updated audience'
    assert p['delivery_profile'] == DEFAULT_DELIVERY
    with pytest.raises(ValueError):
        ws.post('/api/v2/execute', {'brand_id': a['id'], 'plan_id': p['id']}, ALICE)
    with pytest.raises(ValueError):
        ws.post('/api/v2/confirm', {'brand_id': a['id'], 'plan_id': p['id'], 'checksum': 'stale'}, ALICE)
    ws.post('/api/v2/confirm', {'brand_id': a['id'], 'plan_id': p['id'], 'checksum': p['checksum']}, ALICE)
    j = ws.post('/api/v2/execute', {'brand_id': a['id'], 'plan_id': p['id']}, ALICE)
    assert ws.post('/api/v2/execute', {'brand_id': a['id'], 'plan_id': p['id']}, ALICE)['id'] == j['id']
    assert ws._read(a['id'], 'plans', p['id'])['budget']['samples'] == 10
    with pytest.raises(ValueError):
        plan(ws, a['id'], budget={'samples': 61})
    with pytest.raises(ValueError):
        plan(ws, a['id'], budget={'queries': 2, 'samples': 11}, request_id='request1')


def test_clarification_must_complete_before_confirm(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    p = plan(ws, a['id'], keyword='')
    assert not p['ready'] and p['questions']
    with pytest.raises(ValueError):
        ws.post('/api/v2/confirm', {'brand_id': a['id'], 'plan_id': p['id'], 'checksum': p['checksum']}, ALICE)
    clarified = plan(ws, a['id'], keyword='', answers='想了解笔芯兼容如何影响选购')
    assert not clarified['ready'] and not clarified['queries']
    explicit = plan(ws, a['id'], keyword='笔芯兼容', answers='想了解笔芯兼容如何影响选购')
    assert explicit['ready'] and explicit['queries'][0]['keyword'] == '笔芯兼容'


def test_restart_marks_uncertain_and_preserves_legacy(tmp_path):
    legacy = tmp_path / 'workspace' / 'old.json'
    legacy.parent.mkdir()
    legacy.write_text('{"original":true}')
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    j = enqueue(ws, a['id'])
    restarted = WorkspaceV2(tmp_path, start_worker=False)
    assert restarted.get('/api/v2/jobs', {'brand_id': a['id']}, ALICE)['jobs'][0]['status'] == 'interrupted'
    assert restarted.post('/api/v2/execute', {'brand_id': a['id'], 'plan_id': j['plan_id']}, ALICE)['status'] == 'interrupted'
    assert legacy.read_text() == '{"original":true}'


def test_worker_failure_redacted_and_not_retried(tmp_path, pipeline, monkeypatch):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    j = enqueue(ws, a['id'])
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('private-api-key-do-not-leak')
    monkeypatch.setattr(research_v2, 'collect', fail)
    result = ws.process_job(a['id'], j['id'])
    assert result['status'] == 'failed'
    assert 'private-api-key' not in json.dumps(result)
    ws.process_job(a['id'], j['id'])
    assert len(calls) == 1


def test_graph_review_after_restart_role_and_checksum(tmp_path, pipeline):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    j = enqueue(ws, a['id'])
    assert ws.process_job(a['id'], j['id'])['status'] == 'awaiting_review'
    restarted = WorkspaceV2(tmp_path, start_worker=False)
    state = restarted.get('/api/v2/job', {'brand_id': a['id'], 'id': j['id']}, ALICE)
    approval = {'brand_id': a['id'], 'job_id': j['id'], 'checksum': state['revision_checksum'], 'decision': 'approve'}
    with pytest.raises(PermissionError):
        restarted.post('/api/v2/review', approval, ALICE)
    with pytest.raises(ValueError):
        restarted.post('/api/v2/review', {**approval, 'checksum': 'stale'}, REVIEWER)
    approved = restarted.post('/api/v2/review', approval, REVIEWER)
    assert approved['status'] == 'approved' and approved['has_artifact']
    output = restarted.get('/api/v2/artifact', {'brand_id': a['id'], 'id': j['id']}, ALICE)
    assert '家庭分工' in output['markdown']
    assert pipeline['collect'] == 1 and pipeline['edit'] == 1


def test_revision_can_be_fixed_without_recollect_and_approval_gate(tmp_path, pipeline):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    j = enqueue(ws, a['id'])
    ws.process_job(a['id'], j['id'])
    state = ws.job(a['id'], j['id'], ALICE)
    original = copy.deepcopy(state['delivery'])
    state['delivery']['cards'][0]['evidence_ids'] = ['other-brand-id']
    invalid = ws.post('/api/v2/revise', {'brand_id': a['id'], 'job_id': j['id'],
        'checksum': state['revision_checksum'], 'delivery': state['delivery']}, ALICE)
    assert invalid['status'] == 'needs_revision'
    with pytest.raises(ValueError):
        ws.post('/api/v2/review', {'brand_id': a['id'], 'job_id': j['id'],
            'checksum': invalid['revision_checksum'], 'decision': 'approve'}, REVIEWER)
    fixed = ws.post('/api/v2/revise', {'brand_id': a['id'], 'job_id': j['id'],
        'checksum': invalid['revision_checksum'], 'delivery': original}, ALICE)
    approved = ws.post('/api/v2/review', {'brand_id': a['id'], 'job_id': j['id'],
        'checksum': fixed['revision_checksum'], 'decision': 'approve'}, REVIEWER)
    assert approved['status'] == 'approved'
    assert pipeline['collect'] == 1
    assert len(ws._list(a['id'], 'revisions')) == 2


def test_prior_context_same_issue_only_with_feedback(tmp_path, pipeline):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    i = issue(ws, a['id'])
    j = enqueue(ws, a['id'], issue_id=i['id'])
    ws.process_job(a['id'], j['id'])
    state = ws.job(a['id'], j['id'], ALICE)
    ws.post('/api/v2/review', {'brand_id': a['id'], 'job_id': j['id'],
            'checksum': state['revision_checksum'], 'decision': 'approve'}, REVIEWER)
    ws.post('/api/v2/feedback', {'brand_id': a['id'], 'job_id': j['id'],
            'category': 'known', 'note': '旧判断已知，需找不同经验'}, ALICE)
    next_job = enqueue(ws, a['id'], issue_id=i['id'])
    ws.process_job(a['id'], next_job['id'])
    assert pipeline['previous'][-1][0]['feedback'][0]['category'] == 'known'
    other_issue = issue(ws, a['id'])
    assert ws._previous(a['id'], other_issue['id']) == []
    b = brand(ws, 'B')
    assert ws._previous(b['id'], i['id']) == []


def test_explicit_ai_planning_does_not_hold_brand_lock(tmp_path, monkeypatch):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    entered = threading.Event()
    release = threading.Event()
    original = research_v2.create_plan
    def block(brand, task, inputs, **kwargs):
        assert inputs['use_ai']
        entered.set()
        release.wait(5)
        return original(brand, task, {**inputs, 'use_ai': False}, **kwargs)
    monkeypatch.setattr(research_v2, 'create_plan', block)
    result = []
    worker = threading.Thread(target=lambda: result.append(plan(ws, a['id'], use_ai=True, request_id='ai1')))
    worker.start()
    assert entered.wait(2)
    # A read on another thread must complete while the provider call is pending.
    read_done = threading.Event()
    reader = threading.Thread(target=lambda: (ws.brands(ADMIN), read_done.set()))
    reader.start()
    assert read_done.wait(1)
    with pytest.raises(ValueError):
        plan(ws, a['id'], use_ai=True, request_id='ai1')
    release.set()
    worker.join(5)
    reader.join(2)
    assert result[0]['id'] == plan(ws, a['id'], use_ai=True, request_id='ai1')['id']


def test_brand_credentials_rejected_and_editor_cannot_manage(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    with pytest.raises(ValueError):
        ws.post('/api/v2/brand', {'brand_id': a['id'], 'source_config': {'api_key': 'secret'}}, ADMIN)
    assert not ws.get('/api/v2/config', {'brand_id': a['id']}, ALICE)['can_review']


def test_real_editor_graph_two_issues_periods_and_historical_export(tmp_path, monkeypatch):
    from insightbot.signal_desk import editorial_v2
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    i = issue(ws, a['id'])
    current = {'id': 'E1'}
    def collect(plan, run_dir):
        return {'evidence': [{'id': current['id'], 'title': '家庭照护自述',
                    'excerpt': '家人共同参与照护后，作者的生活时间安排有了变化。',
                    'url': 'https://example.org/' + current['id'], 'source_grade': 'full_text'}],
                'collection': {'status': 'complete'}, 'external_context': [], 'ledger': []}
    monkeypatch.setattr(research_v2, 'collect', collect)
    raw = {'value': '\n'.join([
        'CANDIDATE|C01|select|家庭照护影响个人安排|E1|-|有具体情境的理解增量',
        'CARD|C01|signal|个案里的照护分工影响生活安排|该作者的自述说明照护分工改变可支配时间。|为理解家庭责任提供一个具体视角。|仅为个案，不代表群体需求。|-|E1|-',
        'CHECK|C01|yes|yes|yes|yes|yes|yes',
        'SCOPE|限定关键词的社交个案，不代表总体。'])}
    monkeypatch.setattr(editorial_v2, 'model_text', lambda *a, **k: (raw['value'], {'calls': 1}))
    j = enqueue(ws, a['id'], issue_id=i['id'])
    assert ws.process_job(a['id'], j['id'])['status'] == 'awaiting_review'
    first = ws.job(a['id'], j['id'], ALICE)
    assert first['errors'] == []
    ws.post('/api/v2/review', {'brand_id': a['id'], 'job_id': j['id'],
         'decision': 'approve', 'checksum': first['revision_checksum']}, REVIEWER)
    ws.post('/api/v2/feedback', {'brand_id': a['id'], 'job_id': j['id'],
         'category': 'investigate', 'note': '补充家人的不同经验'}, ALICE)
    current['id'] = 'E2'
    raw['value'] = f"LOOKBACK|{j['id']}|新个案支持家庭分工影响时间安排，但仍不能外推到总体。|E2\nSCOPE|本期补充一个不同作者的社交个案，仍缺乏代表性样本。"
    second_job = enqueue(ws, a['id'], issue_id=i['id'])
    assert ws.process_job(a['id'], second_job['id'])['status'] == 'awaiting_review'
    second = ws.job(a['id'], second_job['id'], ALICE)
    assert second['delivery']['cards'] == []
    assert second['delivery']['lookback']['previous_id'] == j['id']
    assert second['errors'] == []
    ws.post('/api/v2/review', {'brand_id': a['id'], 'job_id': second_job['id'],
         'decision': 'approve', 'checksum': second['revision_checksum']}, REVIEWER)
    ws.post('/api/v2/brand', {'brand_id': a['id'], 'name': 'Renamed'}, ADMIN)
    exported = ws.get('/api/v2/artifact', {'brand_id': a['id'], 'id': second_job['id']}, ALICE)
    assert exported['markdown'].startswith('# A ·')
    assert '上期回看' in exported['markdown'] and 'E2' in exported['markdown']


def test_real_editor_empty_collection_is_zero_not_failure(tmp_path, monkeypatch):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    monkeypatch.setattr(research_v2, 'collect', lambda *a, **k: {
        'evidence': [], 'collection': {'status': 'empty'}, 'external_context': [], 'ledger': []})
    j = enqueue(ws, a['id'])
    assert ws.process_job(a['id'], j['id'])['status'] == 'awaiting_review'
    state = ws.job(a['id'], j['id'], ALICE)
    assert state['delivery']['cards'] == [] and state['delivery']['model_usage'] == []
    assert '未取得可引用材料' in state['delivery']['scope']


def test_dialogue_reuses_task_preserves_prior_plan_and_resumes_after_restart(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws, 'Fictional stationery brand')
    first = plan(ws, a['id'], request='用户如何理解笔芯兼容？', keyword='笔芯 兼容')
    turns = [{'role': 'user', 'content': first['task']['request']},
             {'role': 'assistant', 'content': '希望关注哪些使用场景？'},
             {'role': 'user', 'content': '办公替换场景，只看本月。'}]
    second = plan(ws, a['id'], request=first['task']['request'], task_id=first['task_id'],
                  answers=turns[-1]['content'], conversation=turns, keyword='办公 笔芯 兼容')
    assert first['task_id'] == second['task_id']
    assert first['id'] != second['id']
    assert ws.get('/api/v2/plan', {'brand_id': a['id'], 'id': first['id']}, ALICE)['keyword'] == '笔芯 兼容'
    summary = ws.get('/api/v2/conversations', {'brand_id': a['id']}, ALICE)['conversations']
    assert len(summary) == 1 and summary[0]['plan_id'] == second['id']
    assert 'conversation' not in summary[0] and 'brand_snapshot' not in summary[0]
    resumed = WorkspaceV2(tmp_path, start_worker=False).get('/api/v2/conversation',
                   {'brand_id': a['id'], 'id': first['task_id']}, ALICE)
    assert resumed['plan']['conversation'] == turns
    assert resumed['plan']['id'] == second['id'] and not resumed['job_id']
    assert not ws.queue.qsize()


def test_dialogue_cannot_continue_cross_brand_or_change_original_request(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a, b = brand(ws), brand(ws, 'B')
    original = plan(ws, a['id'])
    with pytest.raises(ValueError):
        plan(ws, b['id'], task_id=original['task_id'])
    with pytest.raises(ValueError):
        plan(ws, a['id'], task_id=original['task_id'], request='另一项完全不同的需求')
    with pytest.raises(ValueError):
        ws.get('/api/v2/conversation', {'brand_id': b['id'], 'id': original['task_id']}, ALICE)
    assert len(ws._list(a['id'], 'planning')) == 1
    assert not ws._list(b['id'], 'planning')


def test_failed_dialogue_retains_words_without_retry_or_exposing_provider_error(tmp_path, monkeypatch):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    first = plan(ws, a['id'])
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('private-provider-secret-do-not-reflect')
    monkeypatch.setattr(research_v2, 'create_plan', fail)
    request = {'brand_id': a['id'], 'task_id': first['task_id'], 'request': first['task']['request'],
               'request_id': 'dialogue-failed', 'use_ai': True,
               'conversation': [{'role': 'user', 'content': '先看看办公替换的使用体验。'}]}
    with pytest.raises(RuntimeError):
        ws.post('/api/v2/plan', request, ALICE)
    with pytest.raises(ValueError):
        ws.post('/api/v2/plan', request, ALICE)
    resumed = ws.get('/api/v2/conversation', {'brand_id': a['id'], 'id': first['task_id']}, ALICE)
    assert resumed['pending']['status'] == 'failed'
    assert resumed['pending']['conversation'] == request['conversation']
    assert 'private-provider-secret' not in json.dumps(resumed)
    assert len(calls) == 1 and not ws.queue.qsize()


def test_over_budget_draft_stays_visible_and_can_be_revised_without_running(tmp_path, monkeypatch):
    from insightbot.signal_desk import editorial_v2
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws, 'Fictional stationery brand')
    proposal = {'task_type': 'product', 'keyword': '笔芯 兼容', 'question': '笔芯兼容如何影响选购理解？',
                'queries': [{'keyword': '笔芯 兼容', 'kind': 'focus'},
                            {'keyword': '替换 笔芯', 'kind': 'focus'},
                            {'keyword': '笔芯 不兼容', 'kind': 'challenge'}], 'questions': []}
    calls = []
    def model(*args, **kwargs):
        calls.append(1)
        return json.dumps(proposal), {'calls': 1, 'stage': 'planner'}
    monkeypatch.setattr(editorial_v2, 'model_text', model)
    draft = plan(ws, a['id'], request='笔芯兼容如何影响选购理解？', use_ai=True, keyword='')
    assert not draft['ready'] and draft['needs_revision'] and len(draft['queries']) == 3
    with pytest.raises(ValueError):
        ws.confirm({'brand_id': a['id'], 'plan_id': draft['id'], 'checksum': draft['checksum']}, ALICE)
    revised = plan(ws, a['id'], task_id=draft['task_id'], request=draft['task']['request'],
                   keyword=draft['keyword'], queries=draft['queries'], budget={'queries': 3})
    assert revised['ready'] and revised['task_id'] == draft['task_id']
    assert len(calls) == 1 and not ws.queue.qsize()
    assert ws.conversations(a['id'], ALICE, draft['task_id'])['plan']['id'] == revised['id']


def test_new_plan_does_not_show_previous_run_as_its_result(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    job = enqueue(ws, a['id'])
    first = ws._read(a['id'], 'plans', job['plan_id'])
    revised = plan(ws, a['id'], task_id=first['task_id'])
    resumed = ws.conversations(a['id'], ALICE, first['task_id'])
    assert resumed['plan']['id'] == revised['id'] and resumed['job_id'] is None
    assert resumed['status'] == 'plan_ready'


def test_restarted_dialogue_marks_uncertain_planning_without_retry(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws)
    p = plan(ws, a['id'])
    operation = ws._list(a['id'], 'planning')[0]
    operation.update(status='running')
    ws._save(a['id'], 'planning', operation)
    restarted = WorkspaceV2(tmp_path, start_worker=False)
    resumed = restarted.conversations(a['id'], ALICE, p['task_id'])
    assert resumed['pending']['status'] == 'interrupted'
    assert not restarted.queue.qsize()


def test_full_dialogue_history_outlives_model_context_window(tmp_path):
    ws = WorkspaceV2(tmp_path, start_worker=False)
    a = brand(ws, 'Fictional stationery brand')
    first = plan(ws, a['id'], request='用户如何理解笔芯兼容？', keyword='笔芯 兼容',
                 conversation=[{'role':'user','content':'用户如何理解笔芯兼容？'}])
    transcript = ws.conversations(a['id'], ALICE, first['task_id'])['conversation']
    latest = first
    for number in range(6):
        transcript.append({'role':'user','content':f'这次补充第{number}个办公使用场景。'})
        latest = plan(ws, a['id'], request=first['task']['request'], task_id=first['task_id'],
                      keyword='笔芯 兼容', conversation=transcript[-8:])
        transcript = ws.conversations(a['id'], ALICE, first['task_id'])['conversation']
    assert len(latest['conversation']) == 8
    assert len(transcript) == 14
    assert transcript[0]['content'] == first['task']['request']
    assert [t['content'] for t in transcript if t['role']=='user'][1:] == [f'这次补充第{i}个办公使用场景。' for i in range(6)]
