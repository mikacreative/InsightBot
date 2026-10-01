import json
from pathlib import Path
import pytest
from insightbot.signal_desk.core import Desk, normalize, validate_cards

EVIDENCE = [{'title':'test sample', 'url':'https://example.org/note/1', 'excerpt':'This is a fixture, not a research finding.', 'platform':'test', 'source_id':'1', 'provider':'fixture'}]
BRIEF = {'brand':'Test Brand', 'question':'Test evidence flow'}


def test_persistent_review_and_delivery(tmp_path):
    first = Desk(tmp_path)
    result = first.start('run1', BRIEF, EVIDENCE)
    assert result['status'] == 'awaiting_review'
    assert not (tmp_path / 'runs/run1/brief.md').exists()
    first.connection.close()
    second = Desk(tmp_path)
    result = second.resume('run1', 'approve', 'Tester')
    assert result['status'] == 'delivered_local'
    assert 'fixture' in Path(result['artifact']).read_text()
    with pytest.raises(ValueError):
        second.resume('run1', 'approve', 'Tester')


def test_reject_never_delivers(tmp_path):
    desk = Desk(tmp_path)
    desk.start('rejected', BRIEF, EVIDENCE)
    result = desk.resume('rejected', 'reject', 'Tester')
    assert result['status'] == 'rejected'
    assert not (tmp_path / 'runs/rejected/brief.md').exists()


def test_cross_vendor_dedupe_preserves_enrichment():
    other = {**EVIDENCE[0], 'provider':'second', 'excerpt':'A much longer full body text from another provider.'}
    normalized = normalize(EVIDENCE + [other], 50)
    assert len(normalized) == 1
    assert normalized[0]['providers'] == ['fixture','second']
    assert normalized[0]['excerpt'] == other['excerpt']
    assert len(normalized[0]['snapshots']) == 2
    assert normalized[0]['conflicting_snapshots']


def test_budget_and_path_validation(tmp_path):
    with pytest.raises(ValueError): normalize(EVIDENCE * 51, 50)
    with pytest.raises(ValueError): Desk(tmp_path).status('../../secret')


def test_replay_maps_sources(tmp_path):
    desk = Desk(tmp_path)
    demo = desk.start('demo', BRIEF, EVIDENCE)
    cards = demo['cards']
    cards[0]['evidence_ids'] = ['1']
    replay = desk.start('replay', BRIEF, EVIDENCE, 'replay', cards)
    assert replay['cards'][0]['evidence_ids'][0].startswith('E')
    assert replay['mode'] == 'replay'


def test_quality_rejects_invented_source(tmp_path):
    desk = Desk(tmp_path)
    cards = desk.start('demo', BRIEF, EVIDENCE)['cards']
    cards[0]['evidence_ids'] = ['fabricated']
    with pytest.raises(ValueError): validate_cards(cards, normalize(EVIDENCE,50))


def test_live_missing_config_fails_without_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv('SIGNAL_DESK_AI_API_KEY', raising=False)
    with pytest.raises(ValueError): Desk(tmp_path).start('live', BRIEF, EVIDENCE, 'live')
    assert not (tmp_path / 'runs/live/brief.md').exists()


def test_runs_are_isolated(tmp_path):
    desk = Desk(tmp_path)
    desk.start('first', BRIEF, EVIDENCE)
    desk.start('second', {'brand':'Other','question':'Other'}, [])
    assert desk.status('first')['brief']['brand'] == 'Test Brand'
    assert desk.status('second')['evidence'] == []
    with pytest.raises(ValueError): desk.start('first', BRIEF, EVIDENCE)


def test_invalid_review_does_not_poison_interrupt(tmp_path):
    desk = Desk(tmp_path)
    desk.start('review', BRIEF, EVIDENCE)
    with pytest.raises(ValueError): desk.resume('review', 'approve', '')
    assert desk.resume('review', 'approve', 'Tester')['status'] == 'delivered_local'


def test_url_alias_dedup():
    without_id = {**EVIDENCE[0]}
    without_id.pop('source_id')
    assert len(normalize(EVIDENCE + [without_id], 50)) == 1


def test_justone_failure_does_not_expose_token(monkeypatch):
    from insightbot.signal_desk import providers
    monkeypatch.setenv('JUSTONEAPI_TOKEN', 'secret-fixture')
    def fail(*args, **kwargs):
        raise RuntimeError('https://example.org/?token=secret-fixture')
    monkeypatch.setattr(providers.httpx, 'get', fail)
    with pytest.raises(RuntimeError) as error:
        providers.justone_search('test')
    assert 'secret-fixture' not in str(error.value)


def test_justone_business_failure_is_not_empty(monkeypatch):
    from insightbot.signal_desk import providers
    monkeypatch.setenv('JUSTONEAPI_TOKEN', 'secret-fixture')
    class Response:
        status_code = 200
        def json(self): return {'code':601}
    monkeypatch.setattr(providers.httpx, 'get', lambda *a, **kw: Response())
    with pytest.raises(RuntimeError, match='601'):
        providers.justone_search('test')


def test_verified_search_normalization():
    from insightbot.signal_desk.providers import search_to_input
    result = search_to_input({'query':'test','raw':{'data':{'items':[{'model_type':'note','note':{'id':'abc','title':'Title','desc':'Excerpt','timestamp':1770000000}}]}}}, 'Brand', 'Question')
    assert result['evidence'][0]['source_id'] == 'abc'
    assert result['evidence'][0]['published_at']
    assert result['brief']['brand'] == 'Brand'


def test_changed_schema_fails_not_zero():
    from insightbot.signal_desk.providers import search_to_input
    with pytest.raises(RuntimeError): search_to_input({'query':'test','raw':{'data':[]}}, 'Brand','Question')


def test_collection_scope_survives_checkpoint(tmp_path):
    from insightbot.signal_desk.core import Desk
    desk = Desk(tmp_path)
    result = desk.start('scope', {'brand': 'B', 'question': 'Q'}, [], collection={'page': 1, 'returned_items': 0, 'note_time': None})
    assert result['coverage']['collection_metadata']['page'] == 1
    assert result['coverage']['collection_metadata']['returned_items'] == 0


def test_truncated_ai_response_records_reason_without_retry(tmp_path, monkeypatch):
    from insightbot.signal_desk import core
    for key, value in {'SIGNAL_DESK_AI_BASE_URL':'https://example.org/v1','SIGNAL_DESK_AI_API_KEY':'fixture-secret','SIGNAL_DESK_AI_MODEL':'fixture'}.items():
        monkeypatch.setenv(key,value)
    calls=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs):
            calls.append(1)
            class Response:
                status_code=200
                def json(self): return {'choices':[{'finish_reason':'length','message':{'content':'{"cards":['}}],'usage':{'completion_tokens':8192}}
            return Response()
    monkeypatch.setattr(core.httpx,'Client',Client)
    with pytest.raises(RuntimeError,match='token limit'): core.live_editor(BRIEF, normalize(EVIDENCE,50),tmp_path)
    assert json.loads((tmp_path/'editor-response-meta.json').read_text())['finish_reason']=='length'
    with pytest.raises(RuntimeError,match='uncertain'): core.live_editor(BRIEF,normalize(EVIDENCE,50),tmp_path)
    assert len(calls)==1


def test_glm_editor_bounds_reasoning_and_omits_duplicate_snapshots(tmp_path, monkeypatch):
    from insightbot.signal_desk import core
    for key,value in {'SIGNAL_DESK_AI_BASE_URL':'https://example.org/v1','SIGNAL_DESK_AI_API_KEY':'fixture','SIGNAL_DESK_AI_MODEL':'glm-5.3-flashx'}.items(): monkeypatch.setenv(key,value)
    monkeypatch.delenv('SIGNAL_DESK_AI_REASONING_EFFORT',raising=False)
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs):
            payload=kwargs['json']
            assert payload['reasoning_effort']=='low'
            sent=json.loads(payload['messages'][1]['content'])['evidence'][0]
            assert sent['excerpt']=='unique body' and 'snapshots' not in sent
            class Response:
                status_code=200
                def json(self): return {'choices':[{'finish_reason':'stop','message':{'content':'{"cards":[]}'}}]}
            return Response()
    monkeypatch.setattr(core.httpx,'Client',Client)
    assert core.live_editor(BRIEF,[{'id':'E1','excerpt':'unique body','snapshots':[{'excerpt':'unique body'}]}],tmp_path)==[]


def _signal_card(evidence_id):
    return {'title':'选题', 'disposition':'research', 'observation':'O', 'interpretation':'I', 'brand_relevance':'R',
            'limitations':'L', 'next_step':'N', 'evidence_ids':[evidence_id], 'counter_evidence_ids':[],
            'signal_type':'topic', 'evidence_strength':'medium', 'plan_sections':['v7 第04节'],
            'quotes':[{'evidence_id':evidence_id, 'text':'not a research finding'}], 'recommended_action':'下期选题试用原话'}


def test_signal_fields_validated():
    evidence = normalize(EVIDENCE, 50)
    eid = evidence[0]['id']
    validate_cards([_signal_card(eid)], evidence, require_signal=True)
    for key, value in [('signal_type','trend'), ('evidence_strength','high'), ('plan_sections','v7'),
                       ('quotes',[{'evidence_id':'fabricated','text':'x'}]), ('recommended_action',' ')]:
        with pytest.raises(ValueError): validate_cards([{**_signal_card(eid), key:value}], evidence)
    legacy = {k: v for k, v in _signal_card(eid).items() if k not in ('signal_type','evidence_strength','plan_sections','quotes','recommended_action')}
    validate_cards([legacy], evidence)
    with pytest.raises(ValueError): validate_cards([legacy], evidence, require_signal=True)


def test_live_v2_requires_signal_fields(tmp_path, monkeypatch):
    import insightbot.signal_desk.core as core
    eid = normalize(EVIDENCE, 50)[0]['id']
    card = _signal_card(eid)
    monkeypatch.setattr(core, 'live_editor', lambda *a: [card])
    result = Desk(tmp_path).start('live2', BRIEF, EVIDENCE, 'live')
    assert result['coverage']['prompt_version'] == core.PROMPT_VERSION
    assert core.requires_signal(result)
    approved = Desk(tmp_path).resume('live2', 'approve', 'Tester')
    text = Path(approved['artifact']).read_text()
    assert '选题机会' in text and '证据强度 中' in text and '> not a research finding' in text
    legacy = {k: v for k, v in card.items() if k != 'signal_type'}
    monkeypatch.setattr(core, 'live_editor', lambda *a: [legacy])
    with pytest.raises(ValueError): Desk(tmp_path).start('live-legacy', BRIEF, EVIDENCE, 'live')
    assert not core.requires_signal({'mode':'live', 'coverage':{'prompt_version':'signal-desk-editor-v1'}})


def test_signal_evidence_integrity_rules():
    evidence = normalize(EVIDENCE, 50)
    eid = evidence[0]['id']
    base = _signal_card(eid)
    with pytest.raises(ValueError, match='both support'):
        validate_cards([{**base, 'counter_evidence_ids':[eid]}], evidence)
    with pytest.raises(ValueError, match='verbatim'):
        validate_cards([{**base, 'quotes':[{'evidence_id':eid, 'text':'a paraphrased finding'}]}], evidence)
    validate_cards([{**base, 'quotes':[{'evidence_id':eid, 'text':'“not a  research\nfinding”'}]}], evidence)
    validate_cards([{**base, 'evidence_strength':'strong'}], evidence)


def test_strength_capped_for_comments_and_keyword_echo():
    comment = normalize([{**EVIDENCE[0], 'source_grade':'qiangua comment thread | general'}], 50)
    card = {**_signal_card(comment[0]['id']), 'evidence_strength':'strong'}
    with pytest.raises(ValueError, match='at most medium'): validate_cards([card], comment)
    validate_cards([{**card, 'evidence_strength':'medium'}], comment)
    searched = normalize([{**EVIDENCE[0], 'query':'实现率'}, {**EVIDENCE[0], 'source_id':'2', 'url':'https://example.org/note/2', 'query':'实现率'},
                          {**EVIDENCE[0], 'source_id':'3', 'url':'https://example.org/note/3', 'query':'退保'}], 50)
    echo = {**_signal_card(searched[0]['id']), 'evidence_ids':[e['id'] for e in searched], 'evidence_strength':'strong', 'title':'追问重心是分红实现率'}
    with pytest.raises(ValueError, match='at most medium'): validate_cards([echo], searched)
    validate_cards([{**echo, 'title':'追问集中在能否兑现'}], searched)


def _graded(n, query, grade):
    return [{**EVIDENCE[0], 'source_id':f'{query}{grade}{i}', 'url':f'https://example.org/{query}/{grade}/{i}', 'query':query,
             'source_grade':f'qiangua comment thread | {grade}'} for i in range(n)]


def test_code_owned_stats_and_figure():
    from insightbot.signal_desk.core import evidence_stats, figure_text
    evidence = normalize(_graded(3, '实现率', 'general') + _graded(2, '港险', 'commercial_suspected') + _graded(1, '港险', 'general'), 50)
    stats = evidence_stats(evidence)
    assert stats['all'] == 6 and stats['general'] == 4 and stats['commercial'] == 2
    assert stats['query:港险'] == 3 and stats['query:实现率:general'] == 3
    general = [e['id'] for e in evidence if e['source_grade'].endswith('general')]
    commercial = [e['id'] for e in evidence if 'commercial' in e['source_grade']]
    card = {**_signal_card(general[0]), 'quotes':[], 'figure':{'label':'模板评论', 'evidence_ids':commercial, 'denominator':'all'}}
    validate_cards([card], evidence)
    assert figure_text(card['figure'], evidence) == '模板评论：2/6'
    for figure in ({**card['figure'], 'denominator':'general'}, {**card['figure'], 'denominator':'invented'},
                   {**card['figure'], 'evidence_ids':commercial * 2}, {**card['figure'], 'evidence_ids':[]}):
        with pytest.raises(ValueError, match='[Ff]igure'): validate_cards([{**card, 'figure':figure}], evidence)


def test_editor_receives_stats_and_compact_collection(tmp_path, monkeypatch):
    from insightbot.signal_desk import core
    for key, value in {'SIGNAL_DESK_AI_BASE_URL':'https://example.org/v1','SIGNAL_DESK_AI_API_KEY':'fixture','SIGNAL_DESK_AI_MODEL':'fixture'}.items():
        monkeypatch.setenv(key, value)
    sent = {}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            sent.update(json)
            class Response:
                status_code = 200
                def json(self): return {'choices':[{'finish_reason':'stop','message':{'content':'{"cards":[]}'}}]}
            return Response()
    monkeypatch.setattr(core.httpx, 'Client', Client)
    evidence = normalize(_graded(2, '换汇', 'general'), 50)
    collection = {'provider':'fixture', 'note_search_coverage_only':{'换汇':{'total_count':9, 'sample_titles':['x']}}}
    core.live_editor(BRIEF, evidence, tmp_path, collection)
    body = json.loads(sent['messages'][1]['content'])
    assert body['evidence_stats']['query:换汇:general'] == 2
    assert body['collection']['note_search_coverage_only']['换汇'] == {'total_count':9}
    assert body['evidence'][0]['query'] == '换汇'
