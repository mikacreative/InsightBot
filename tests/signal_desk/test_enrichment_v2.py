"""Gap-directed research, spend bounds and review recovery with fictional data."""
import copy
import hashlib
import json
import threading

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="Install requirements-signal-desk.txt for the isolated Signal Desk runtime")

from insightbot.signal_desk import editorial_v2 as e, research_v2 as r
from insightbot.signal_desk.workspace_v2 import WorkspaceV2


BRAND = {'id': 'fictional-stationery', 'name': '北辰文具（虚构）'}
TASK = {'id': 'task1', 'request': '理解替换笔芯的兼容说明为何让用户困惑'}
EVIDENCE = [{'id': 'E1', 'title': '替换笔芯的兼容问题', 'excerpt': '替换笔芯的兼容问题',
             'url': 'https://www.xiaohongshu.com/explore/n1', 'source_id': 'n1',
             'providers': ['qiangua'], 'source_grade': 'note_meta', 'query': '笔芯兼容',
             'snapshots': [{'provider': 'qiangua', 'excerpt': '替换笔芯的兼容问题'}]}]
GAP = {'candidate_id': 'C01', 'evidence_ids': ['E1'], 'gap': '未读正文，无法判断兼容困惑来自型号还是规格表达',
       'expected_change': '正文有具体经历才可能作为个案入选，否则保留线索'}
GAP_TEXT = '\n'.join([
    'CANDIDATE|C01|research|兼容表达可能让选购产生困惑|E1|-|标题不足以判断具体原因',
    'GAP|C01|E1|未读正文，无法区分型号与规格表达|具体经历可改变个案是否入选',
    'SCOPE|本轮限定笔芯相关查询；仅有标题，尚不能形成精选判断。'])
SELECTED_TEXT = '\n'.join([
    'CANDIDATE|C01|select|兼容表达需要具体到笔杆型号|E1|-|正文提供了具体困惑',
    'CARD|C01|signal|这个个案的困惑在笔杆适配|作者说明选购替换笔芯时难以确认笔杆型号是否兼容。|为检查现有兼容说明提供一个具体视角。|单一个案，不代表所有购买者。|-|E1,E2|-',
    'CHECK|C01|yes|yes|yes|yes|yes|yes',
    'SCOPE|限定关键词的千瓜内容样本；补读了相关正文，不代表总体。'])


def plan(**budget):
    return r.create_plan(BRAND, TASK, {'keyword': '笔芯兼容', 'budget': budget})


# 千瓜 detail was measured on 2026-10-11 to return note metadata only (40 fields, no content
# field at all), so a 千瓜-only run cannot produce a claim-supporting body. A deliverable card
# therefore also has to cite one note_body item, and only JustOneAPI get-note-detail yields it.
BODY = {'id': 'E2', 'title': '替换笔芯的兼容问题', 'excerpt': '笔杆型号刻在笔夹内侧，我按型号对照表才确认兼容。',
        'url': 'https://www.xiaohongshu.com/explore/n2', 'source_id': 'n2', 'providers': ['justoneapi'],
        'source_grade': 'note_body', 'query': '笔芯兼容',
        'snapshots': [{'provider': 'justoneapi', 'excerpt': '笔杆型号刻在笔夹内侧，我按型号对照表才确认兼容。'}]}


def collected_with_body():
    return {**collected(), 'evidence': copy.deepcopy(EVIDENCE) + [copy.deepcopy(BODY)]}


def collected():
    return {'evidence': copy.deepcopy(EVIDENCE), 'collection': {'status': 'complete', 'errors': []},
            'external_context': [], 'ledger': []}


def draft(calls=1):
    return {**e.parse_protocol(GAP_TEXT), 'model_usage': [{'calls': 1}] * calls}


class Adapter:
    def __init__(self, response=None, fail=False):
        self.details = []
        self.response = response
        self.fail = fail

    def auth(self):
        return True

    def search(self, query, **kwargs):
        return {'normalized_items': [{'title': EVIDENCE[0]['title'], 'url': EVIDENCE[0]['url'],
                 'raw': {'NoteId': 'n1'}}]}

    def detail(self, url):
        self.details.append(url)
        if self.fail:
            raise r.SourceError('private-cookie-do-not-leak')
        return self.response or {'normalized_note': {'title': '笔芯兼容个案',
            'raw': {'NoteId': 'n1', 'Content': '选购替换笔芯时，我难以确认笔杆型号是否兼容。'}}}


def test_new_plan_reserves_reads_and_legacy_frozen_plan_keeps_initial_reads(tmp_path):
    adapter = Adapter()
    p = plan(body_reads=1)
    assert p['budget']['enrichment_rounds'] == 1
    result = r.collect(p, tmp_path / 'new', adapter=adapter)
    assert not adapter.details and result['collection']['bodies'] == 0
    del p['budget']['enrichment_rounds']
    old = r.collect(p, tmp_path / 'old', adapter=adapter)
    assert len(adapter.details) == 1 and old['collection']['summary_only'] == 1
    assert r.enrich(p, collected(), draft(), tmp_path / 'frozen', adapter=adapter)['enrichment']['reason'] == 'round_limit'
    assert len(adapter.details) == 1


@pytest.mark.parametrize('change', [
    {'evidence_ids': ['other-brand']}, {'evidence_ids': ['E1', 'E1']}, {'gap': ''},
    {'candidate_id': 'C99'}, {'url': 'https://other.test'}, {'candidate_id': []},
])
def test_gap_cannot_expand_sources_or_omit_specific_reason(change):
    request = {**GAP, **change}
    with pytest.raises(ValueError):
        r.validate_enrichment_requests([request], EVIDENCE, draft()['candidates'])


def test_gap_must_link_research_candidate_and_qiangua_title(tmp_path):
    initial = draft()
    initial['candidates'][0]['disposition'] = 'select'
    with pytest.raises(ValueError, match='待研究'):
        r.enrich(plan(), collected(), initial, tmp_path)
    assert any('未知' in error for error in e.validate_edition(
        {**draft(), 'enrichment_requests': [{**GAP, 'evidence_ids': ['other-brand']}]}, EVIDENCE))
    for evidence in ([{**EVIDENCE[0], 'providers': ['rss']}], [{**EVIDENCE[0], 'source_grade': 'note_segment'}]):
        with pytest.raises(ValueError, match='千瓜'):
            r.validate_enrichment_requests([GAP], evidence, draft()['candidates'])
    with pytest.raises(ValueError, match='唯一'):
        r.validate_enrichment_requests([GAP, GAP], EVIDENCE, draft()['candidates'])


def test_enrichment_retains_ids_snapshots_and_cache_binding(tmp_path):
    original = collected()
    before = copy.deepcopy(original)
    adapter = Adapter()
    result = r.enrich(plan(), original, draft(), tmp_path, adapter=adapter)
    assert original == before
    source = result['evidence'][0]
    assert source['id'] == 'E1' and source['source_id'] == 'n1'
    assert source['source_grade'] == 'note_segment' and len(source['snapshots']) == 2
    assert source['snapshots'][0]['excerpt'] == EVIDENCE[0]['excerpt']
    assert result['enrichment']['attempted'] == 1
    assert result['enrichment']['outcomes'][0]['status'] == 'text_added'
    assert r.enrich(plan(), original, draft(), tmp_path, adapter=adapter) == result
    assert len(adapter.details) == 1
    changed = draft()
    changed['enrichment_requests'][0]['gap'] = '不同缺口'
    with pytest.raises(ValueError, match='不同输入'):
        r.enrich(plan(), original, changed, tmp_path, adapter=adapter)


def test_normalized_blank_url_is_filled_only_after_raw_identity_check(tmp_path):
    adapter = Adapter(response={'normalized_note': {'url': '', 'raw': {'NoteId': 'n1', 'Content': '真实返回的正文格式，虚构文本。'}}})
    result = r.enrich(plan(), collected(), draft(), tmp_path, adapter=adapter)
    assert result['evidence'][0]['id'] == 'E1'
    assert result['evidence'][0]['source_grade'] == 'note_segment'
    assert result['enrichment']['outcomes'][0]['status'] == 'text_added'


@pytest.mark.parametrize('budget,reason', [
    ({'enrichment_rounds': 0}, 'round_limit'), ({'body_reads': 0}, 'body_budget'),
    ({'model_calls': 1}, 'model_budget'),
])
def test_budget_exhaustion_does_not_call_source(tmp_path, budget, reason):
    adapter = Adapter()
    result = r.enrich(plan(**budget), collected(), draft(), tmp_path, adapter=adapter)
    assert not adapter.details and result['enrichment']['reason'] == reason


def test_body_allowance_is_shared_and_same_source_is_read_once(tmp_path):
    initial, research = collected(), draft()
    initial['evidence'].append({**copy.deepcopy(EVIDENCE[0]), 'id': 'E2'})
    research['candidates'].append({**research['candidates'][0], 'id': 'C02', 'evidence_ids': ['E2']})
    research['enrichment_requests'].append({**GAP, 'candidate_id': 'C02', 'evidence_ids': ['E2']})
    initial['ledger'].append({'operation': 'note.search_by_url', 'url': 'https://www.xiaohongshu.com/explore/old', 'status': 'failed'})
    adapter = Adapter()
    result = r.enrich(plan(body_reads=2), initial, research, tmp_path, adapter=adapter)
    assert len(adapter.details) == 1
    assert len([r for r in result['ledger'] if r['operation'] == 'note.search_by_url']) == 2
    assert [s['id'] for s in result['evidence']] == ['E1', 'E2']
    assert all(s['source_grade'] == 'note_segment' for s in result['evidence'])
    assert result['enrichment']['outcomes'][0]['candidate_ids'] == ['C01', 'C02']


@pytest.mark.parametrize('response,status', [
    ({'normalized_note': {'title': '仍只有标题'}}, 'no_text'),
    ({'normalized_note': {'url': 'https://www.xiaohongshu.com/explore/another', 'raw': {'Content': '别的正文'}}}, 'failed'),
    ({'normalized_note': {'url': EVIDENCE[0]['url'], 'raw': {'Url': 'https://www.xiaohongshu.com/explore/another', 'Content': '别的正文'}}}, 'failed'),
    ({'normalized_note': {'raw': {'NoteId': 'another', 'Content': '别的正文'}}}, 'failed'),
])
def test_incomplete_or_mismatched_body_never_upgrades_evidence(tmp_path, response, status):
    adapter = Adapter(response=response)
    result = r.enrich(plan(), collected(), draft(), tmp_path, adapter=adapter)
    assert result['evidence'][0]['source_grade'] == 'note_meta'
    assert result['enrichment']['outcomes'][0]['status'] == status
    assert result['enrichment']['status'] == 'partial'


def test_failed_and_unknown_requests_are_not_resent_or_exposed(tmp_path):
    adapter = Adapter(fail=True)
    result = r.enrich(plan(), collected(), draft(), tmp_path / 'failed', adapter=adapter)
    assert result['collection']['status'] == 'partial'
    assert 'private-cookie' not in json.dumps(result)
    assert r.enrich(plan(), collected(), draft(), tmp_path / 'failed', adapter=adapter) == result
    assert len(adapter.details) == 1
    directory = tmp_path / 'unknown'
    directory.mkdir()
    key = hashlib.sha256(r._source_url(EVIDENCE[0]['url']).encode()).hexdigest()[:24]
    (directory / f'enrich-detail-{key}.started').touch()
    unknown = r.enrich(plan(), collected(), draft(), directory, adapter=adapter)
    assert unknown['enrichment']['outcomes'][0]['status'] == 'unknown'
    assert unknown['collection']['status'] == 'partial'
    assert len(adapter.details) == 1


def test_private_records_publish_atomically_and_interrupted_write_preserves_old_value(tmp_path, monkeypatch):
    path = tmp_path / 'source-ledger.json'
    r.private_json(path, {'status': 'before'})
    entered, release = threading.Event(), threading.Event()
    original_dump = r.json.dump
    def delayed_dump(value, handle, **kwargs):
        handle.write(' ')
        entered.set()
        assert release.wait(3)
        return original_dump(value, handle, **kwargs)
    monkeypatch.setattr(r.json, 'dump', delayed_dump)
    writer = threading.Thread(target=lambda: r.private_json(path, {'status': 'after'}))
    writer.start()
    assert entered.wait(2)
    try:
        for _ in range(10):
            assert json.loads(path.read_text()) == {'status': 'before'}
    finally:
        release.set()
        writer.join(3)
    assert json.loads(path.read_text()) == {'status': 'after'}
    assert path.stat().st_mode & 0o777 == 0o600
    def interrupted_dump(value, handle, **kwargs):
        handle.write('{')
        raise OSError('simulated interrupted write')
    monkeypatch.setattr(r.json, 'dump', interrupted_dump)
    with pytest.raises(OSError):
        r.private_json(path, {'status': 'partial'})
    assert json.loads(path.read_text()) == {'status': 'after'}
    assert not list(tmp_path.glob('*.tmp'))


def test_all_execution_edits_share_model_allowance_and_do_not_repeat_gap(tmp_path):
    p, source = plan(model_calls=3), collected_with_body()
    calls = []
    def editor(prompt, payload):
        calls.append(payload)
        return 'invalid' if len(calls) == 1 else GAP_TEXT
    first = e.edit(p, source, run_dir=tmp_path, editor=editor)
    assert len(first['model_usage']) == 2
    supplemented = r.enrich(p, source, first, tmp_path, adapter=Adapter())
    final = e.edit(p, supplemented, run_dir=tmp_path, stage='reedit', prior_model_usage=first['model_usage'],
                   previous_draft=first, editor=lambda prompt, payload: SELECTED_TEXT)
    assert [row['stage'] for row in final['model_usage']] == ['editor', 'repair', 'reedit']
    with pytest.raises(ValueError, match='额度'):
        e.edit(p, supplemented, run_dir=tmp_path, stage='reedit', prior_model_usage=final['model_usage'])
    with pytest.raises(ValueError, match='未通过'):
        e.edit(p, supplemented, run_dir=tmp_path / 'invalid', stage='reedit',
               prior_model_usage=first['model_usage'], editor=lambda *_: GAP_TEXT)


def test_model_stages_have_distinct_bound_caches_and_unknown_is_not_retried(tmp_path, monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, **kwargs):
            calls.append(kwargs['json'])
            class Response:
                status_code = 200
                def json(self):
                    return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'SCOPE|测试'}}]}
            return Response()
    monkeypatch.setenv('SIGNAL_DESK_AI_BASE_URL', 'https://model.example.test')
    monkeypatch.setenv('SIGNAL_DESK_AI_API_KEY', 'fictional-test-key')
    monkeypatch.setenv('SIGNAL_DESK_AI_MODEL', 'fictional-test-model')
    monkeypatch.setattr(e.httpx, 'Client', Client)
    first = e.model_text('p', {'v': 1}, tmp_path, 'editor')
    assert e.model_text('p', {'v': 1}, tmp_path, 'editor') == first
    e.model_text('p', {'v': 2}, tmp_path, 'reedit')
    assert len(calls) == 2
    with pytest.raises(ValueError, match='绑定'):
        e.model_text('p', {'v': 2}, tmp_path, 'editor')
    (tmp_path / 'reedit-repair-v2.started').touch()
    with pytest.raises(RuntimeError, match='未知'):
        e.model_text('p', {'v': 3}, tmp_path, 'reedit-repair')
    assert len(calls) == 2


def test_graph_gap_to_selection_review_export_and_restart(tmp_path, monkeypatch):
    admin = {'username': 'admin', 'role': 'admin'}
    ws = WorkspaceV2(tmp_path, start_worker=False)
    brand = ws.save_brand({'name': BRAND['name']}, admin, create=True)
    p = ws.create_plan({'brand_id': brand['id'], 'request': TASK['request'], 'keyword': '笔芯兼容'}, admin)
    ws.confirm({'brand_id': brand['id'], 'plan_id': p['id'], 'checksum': p['checksum']}, admin)
    job = ws.execute({'brand_id': brand['id'], 'plan_id': p['id']}, admin)
    monkeypatch.setattr(r, 'collect', lambda *args: collected_with_body())
    adapter = Adapter()
    monkeypatch.setattr(r, 'QianguaAdapter', lambda: adapter)
    stages = []
    def model(prompt, payload, run_dir, stage, **kwargs):
        stages.append(stage)
        if stage == 'reedit':
            assert payload['evidence'][0]['source_grade'] == 'note_segment'
            assert payload['previous_draft']['candidates'][0]['disposition'] == 'research'
            assert payload['enrichment_policy']['allowed'] is False
        return (GAP_TEXT if stage == 'editor' else SELECTED_TEXT), {'stage': stage, 'calls': 1}
    monkeypatch.setattr(e, 'model_text', model)
    assert ws.process_job(brand['id'], job['id'])['status'] == 'awaiting_review'
    state = ws.job(brand['id'], job['id'], admin)
    assert not state['errors'] and state['enrichment']['attempted'] == 1
    assert state['evidence'][0]['id'] == 'E1'
    assert state['delivery']['cards'][0]['candidate_id'] == 'C01'
    restarted = WorkspaceV2(tmp_path, start_worker=False)
    approved = restarted.review({'brand_id': brand['id'], 'job_id': job['id'], 'decision': 'approve',
                                 'checksum': state['revision_checksum']}, admin)
    artifact = restarted.get('/api/v2/artifact', {'brand_id': brand['id'], 'id': job['id']}, admin)
    assert approved['status'] == 'approved' and '笔杆适配' in artifact['markdown']
    assert 'GAP' not in artifact['markdown'] and '预期改变' not in artifact['markdown']
    assert stages == ['editor', 'reedit'] and len(adapter.details) == 1
    for status in ('enriching', 'reediting'):
        restarted._phase(brand['id'], job['id'], status)
        recovered = WorkspaceV2(tmp_path, start_worker=False)
        assert recovered.job(brand['id'], job['id'], admin)['status'] == 'interrupted'
    assert stages == ['editor', 'reedit'] and len(adapter.details) == 1


@pytest.mark.parametrize('failure', [False, True])
def test_graph_unresolved_gap_keeps_zero_cards_and_discloses_fetch_failure(tmp_path, monkeypatch, failure):
    admin = {'username': 'admin', 'role': 'admin'}
    ws = WorkspaceV2(tmp_path, start_worker=False)
    brand = ws.save_brand({'name': BRAND['name']}, admin, create=True)
    p = ws.create_plan({'brand_id': brand['id'], 'request': TASK['request'], 'keyword': '笔芯兼容'}, admin)
    ws.confirm({'brand_id': brand['id'], 'plan_id': p['id'], 'checksum': p['checksum']}, admin)
    job = ws.execute({'brand_id': brand['id'], 'plan_id': p['id']}, admin)
    monkeypatch.setattr(r, 'collect', lambda *args: collected())
    adapter = Adapter(response={'normalized_note': {'title': '仍无正文'}}, fail=failure)
    monkeypatch.setattr(r, 'QianguaAdapter', lambda: adapter)
    calls = []
    def model(prompt, payload, run_dir, stage, **kwargs):
        calls.append(stage)
        if stage == 'editor':
            raw = GAP_TEXT
        else:
            assert payload['evidence'][0]['source_grade'] == 'note_meta'
            assert bool(payload['collection']['errors']) is failure
            raw = GAP_TEXT.split('\nGAP|')[0] + '\nSCOPE|' + (
                '正文补读失败，缺口仍未解决，未形成精选判断。' if failure else '接口未提供正文，缺口仍未解决，未形成精选判断。')
        return raw, {'stage': stage, 'calls': 1}
    monkeypatch.setattr(e, 'model_text', model)
    assert ws.process_job(brand['id'], job['id'])['status'] == 'awaiting_review'
    state = ws.job(brand['id'], job['id'], admin)
    assert state['delivery']['cards'] == [] and state['delivery']['candidates'][0]['disposition'] == 'research'
    assert state['enrichment']['outcomes'][0]['status'] == ('failed' if failure else 'no_text')
    assert len(adapter.details) == 1 and calls == ['editor', 'reedit']
