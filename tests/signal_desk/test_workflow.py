import json
from pathlib import Path
import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="Install requirements-signal-desk.txt for the isolated Signal Desk runtime")
from insightbot.signal_desk.core import Desk, normalize, number_flags, render, validate_cards

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


@pytest.mark.parametrize('title_first', [True, False])
@pytest.mark.parametrize('title_excerpt', ['仅有标题', '仅有标题，不能作为正文证据。' * 20],
                         ids=['short-title', 'long-title'])
def test_duplicate_body_replaces_title_grade_and_matching_excerpt(title_first, title_excerpt):
    title = {**EVIDENCE[0], 'excerpt': title_excerpt, 'source_grade': 'note_meta',
             'limitation': 'Only the title was retrieved'}
    body = {**EVIDENCE[0], 'provider': 'qiangua', 'excerpt': '虚构使用个案：这支笔在通勤时容易携带。',
            'source_grade': 'note_segment', 'limitation': 'One fictional text sample'}
    items = [title, body] if title_first else [body, title]
    merged = normalize(items, 50)[0]
    assert merged['id'] == normalize([title], 50)[0]['id']
    assert merged['source_grade'] == 'note_segment'
    assert merged['excerpt'] == body['excerpt']
    assert merged['limitation'] == body['limitation']
    assert len(merged['snapshots']) == 2


def test_legacy_grade_tokens_still_resolve():
    """Stored runs written before the 2026-10-11 vocabulary change must keep their meaning."""
    from insightbot.signal_desk import grades
    assert grades.level('title_only') == 'note_meta'
    assert grades.level('search_snippet') == 'note_segment'
    assert grades.level('search excerpt') == 'note_segment'
    assert grades.level('qiangua_body') == 'note_segment'
    assert grades.level('full_text') == 'note_body'
    assert grades.level('rss_snippet') == grades.EXTERNAL_CONTEXT
    assert grades.kind('qiangua comment thread | general') == 'general'


def test_unknown_grade_fails_closed():
    """An unrecognised token must never rank above a title or escape the summary guard."""
    from insightbot.signal_desk import grades
    for token in ('search excerpt v9', 'note_body_v2', '', None, 'totally new vendor grade'):
        assert grades.level(token) == grades.UNVERIFIED
        assert grades.rank(token) == 0
        assert grades.summary_only(token) is True
        assert grades.is_body(token) is False


def test_empty_duplicate_does_not_upgrade_meta_to_segment():
    title = {**EVIDENCE[0], 'source_grade': 'note_meta', 'limitation': 'Only a fictional title'}
    empty = {**title, 'provider': 'qiangua', 'source_grade': 'note_segment', 'excerpt': '  ',
             'limitation': 'No usable text returned'}
    merged = normalize([title, empty], 50)[0]
    assert merged['source_grade'] == 'note_meta'
    assert merged['excerpt'] == title['excerpt']
    assert merged['limitation'] == title['limitation']


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
    result = search_to_input({'query':'test','raw':{'code':0,'data':{'notes':[
        {'id':'abc','title':'Title','desc':'Excerpt','timestamp':1770000000}],'has_more':False,'total':1}}}, 'Brand', 'Question')
    evidence = result['evidence'][0]
    assert evidence['source_id'] == 'abc'
    assert evidence['published_at']
    assert result['brief']['brand'] == 'Brand'


def test_search_summary_is_graded_as_segment_not_body():
    """A truncated search desc must be summary-only, so the editorial guard rejects it as sole support."""
    from insightbot.signal_desk.providers import search_to_input
    from insightbot.signal_desk import grades
    result = search_to_input({'query':'test','raw':{'code':0,'data':{'notes':[
        {'id':'abc','desc':'Excerpt','timestamp':1770000000}],'has_more':False,'total':1}}}, 'Brand', 'Question')
    evidence = result['evidence'][0]
    assert evidence['source_grade'] == 'note_segment'
    assert evidence['body_verified'] is False
    assert grades.summary_only(evidence['source_grade']) is True
    assert grades.is_body(evidence['source_grade']) is False
    assert grades.rank(evidence['source_grade']) < grades.rank('note_body')


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
    assert core.live_editor(BRIEF,[{'id':'E1','excerpt':'unique body','snapshots':[{'excerpt':'unique body'}]}],tmp_path)['cards']==[]


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
    monkeypatch.setattr(core, 'live_editor', lambda *a: {'headline':'港险被当作高息定存卖', 'avoid':['不用“收益稳”话术'], 'cards':[card]})
    result = Desk(tmp_path).start('live2', BRIEF, EVIDENCE, 'live')
    assert result['coverage']['prompt_version'] == core.PROMPT_VERSION
    assert core.requires_signal(result)
    approved = Desk(tmp_path).resume('live2', 'approve', 'Tester')
    text = Path(approved['artifact']).read_text()
    assert '选题机会' in text and '证据强度 中' in text and '> not a research finding' in text
    legacy = {k: v for k, v in card.items() if k != 'signal_type'}
    monkeypatch.setattr(core, 'live_editor', lambda *a: {'headline':'h', 'avoid':[], 'cards':[legacy]})
    with pytest.raises(ValueError): Desk(tmp_path).start('live-legacy', BRIEF, EVIDENCE, 'live')
    assert not core.requires_signal({'mode':'live', 'coverage':{'prompt_version':'signal-desk-editor-v1'}})


def test_degenerate_and_keyword_figures_are_rejected():
    evidence = normalize(_graded(2, '换汇', 'comment|general') + _graded(2, '实现率', 'comment|general'), 50)
    a, b, c, d = [e['id'] for e in evidence]
    base = _signal_card(a)
    whole = {**base, 'figure':{'label':'换汇相关评论', 'evidence_ids':[a, b], 'denominator':'query:换汇:general'}}
    with pytest.raises(ValueError, match='re-counts its own search'):
        validate_cards([whole], evidence, require_signal=True)
    rate = {**base, 'figure':{'label':'命中实现率的评论', 'evidence_ids':[c, d], 'denominator':'general'}}
    with pytest.raises(ValueError, match='measures the search'):
        validate_cards([rate], evidence, require_signal=True)
    real = {**base, 'figure':{'label':'一般样本中的换汇提问', 'evidence_ids':[a], 'denominator':'general'}}
    assert validate_cards([real], evidence, require_signal=True)[0]['figure']['label'] == '一般样本中的换汇提问'


def test_number_flags_are_recorded_not_fatal():
    from insightbot.signal_desk.core import number_flags
    card = {**_signal_card('E1'), 'observation':'一般样本中9条命中', 'recommended_action':'第04节替换示意'}
    flags = number_flags([card], {'headline':'相关0条', 'avoid':['不足5条', '不要渲染焦虑']})
    assert [f['field'] for f in flags] == ['observation', 'recommended_action', 'summary.headline', 'summary.avoid']


def test_quality_records_number_flags(tmp_path, monkeypatch):
    import insightbot.signal_desk.core as core
    eid = normalize(EVIDENCE, 50)[0]['id']
    card = {**_signal_card(eid), 'observation':'一般样本中9条命中'}
    monkeypatch.setattr(core, 'live_editor', lambda *a: {'headline':'h', 'avoid':[], 'cards':[card]})
    result = Desk(tmp_path).start('flagged', BRIEF, EVIDENCE, 'live')
    assert result['status'] == 'awaiting_review'
    assert result['number_flags'][0]['field'] == 'observation'
    assert '数字自查' in render(result)
    flags = number_flags(result['cards'], result.get('summary'))
    (tmp_path / 'runs/flagged/number-flags.json').write_text(json.dumps(flags))
    assert json.loads((tmp_path / 'runs/flagged/number-flags.json').read_text())[0]['field'] == 'observation'


def test_live_invalid_ai_figure_is_dropped_not_fatal(tmp_path, monkeypatch):
    import insightbot.signal_desk.core as core
    eid = normalize(EVIDENCE, 50)[0]['id']
    bad = {**_signal_card(eid), 'figure':{'label':'未采集词', 'evidence_ids':[], 'denominator':'query:invented:general'}}
    good = {**_signal_card(eid), 'figure':{'label':'全部', 'evidence_ids':[eid], 'denominator':'all'}}
    monkeypatch.setattr(core, 'live_editor', lambda *a: {'headline':'h', 'avoid':[], 'cards':[bad, good]})
    result = Desk(tmp_path).start('live-fig', BRIEF, EVIDENCE, 'live')
    assert result['status'] == 'awaiting_review'
    assert result['cards'][0]['figure'] is None and result['cards'][1]['figure']['denominator'] == 'all'
    drops = json.loads(next(tmp_path.rglob('figure-drops.json')).read_text())
    assert drops[0]['card'] == 0 and 'denominator' in drops[0]['reason']
    with pytest.raises(ValueError): validate_cards([bad], normalize(EVIDENCE, 50), require_signal=True)


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
    return [{**EVIDENCE[0], 'title':f'{query} sample {i}', 'source_id':f'{query}{grade}{i}', 'url':f'https://example.org/{query}/{grade}/{i}', 'query':query,
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


def test_live_v2_requires_summary(tmp_path, monkeypatch):
    import insightbot.signal_desk.core as core
    card = _signal_card(normalize(EVIDENCE, 50)[0]['id'])
    monkeypatch.setattr(core, 'live_editor', lambda *a: {'cards':[card]})
    with pytest.raises(ValueError, match='headline'): Desk(tmp_path).start('nohead', BRIEF, EVIDENCE, 'live')
    assert Desk(tmp_path).start('empty', BRIEF, [], 'live')['status'] == 'awaiting_review'


def test_marketing_view_is_one_page(tmp_path, monkeypatch):
    import insightbot.signal_desk.core as core
    evidence = normalize(_graded(2, '港险', 'commercial_suspected') + _graded(1, '实现率', 'general'), 50)
    commercial = [e['id'] for e in evidence if 'commercial' in e['source_grade']]
    keep = {**_signal_card(commercial[0]), 'evidence_strength':'medium', 'signal_type':'messaging_risk',
            'figure':{'label':'代理人模板评论', 'evidence_ids':commercial, 'denominator':'all'}}
    dropped = {**_signal_card(commercial[0]), 'title':'不该出现的卡', 'disposition':'drop', 'evidence_strength':'weak'}
    raw = _graded(2, '港险', 'commercial_suspected') + _graded(1, '实现率', 'general')
    monkeypatch.setattr(core, 'live_editor', lambda *a: {'headline':'港险在小红书被当作高息定存卖', 'avoid':['不用“收益稳”话术'], 'cards':[keep, dropped]})
    desk = Desk(tmp_path)
    desk.start('mkt', {**BRIEF, 'time_window':'2026-09'}, raw, 'live')
    text = core.render_marketing(desk.status('mkt'))
    assert '**一句话结论**：港险在小红书被当作高息定存卖' in text and '话术风险 · 证据强度 中' in text
    assert '代理人模板评论：2/3' in text and '> “not a research finding”' in text and '- 不用“收益稳”话术' in text
    assert '不该出现的卡' not in text and 'observation' not in text and '一般 1 / 商业 2' in text and '未经人工批准' in text
    approved = desk.resume('mkt', 'approve', 'Tester')
    marketing = (Path(approved['artifact']).parent / 'marketing.md').read_text()
    assert '审稿 Tester' in marketing
