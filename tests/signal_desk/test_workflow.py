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
