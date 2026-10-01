import json
from pathlib import Path

import pytest

from insightbot.signal_desk import context
from insightbot.signal_desk.core import Desk, normalize

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'rss'


class Response:
    def __init__(self, text):
        self.content = text.encode() if isinstance(text, str) else text
    def raise_for_status(self):
        return None


def test_load_context_config_shapes(tmp_path, monkeypatch):
    monkeypatch.delenv('SIGNAL_DESK_CONTEXT_CONFIG', raising=False)
    assert context.load_context_config() == {}
    with pytest.raises(ValueError, match='not found'):
        context.load_context_config(str(tmp_path / 'missing.json'))
    bad = tmp_path / 'bad.json'; bad.write_text('{oops')
    with pytest.raises(ValueError, match='not valid JSON'):
        context.load_context_config(str(bad))
    good = tmp_path / 'ok.json'
    good.write_text(json.dumps({'rss': [{'id': 'a', 'name': 'A', 'url': 'https://x.com/feed', 'tags': ['营销']},
                                        {'url': '   '}, 'nonsense'],
                               'search': {'enabled': True, 'provider': 'duckduckgo', 'queries': ['Q']}}))
    cfg = context.load_context_config(str(good))
    assert cfg['rss'] == [{'id': 'a', 'name': 'A', 'url': 'https://x.com/feed', 'tags': ['营销']}]
    assert cfg['search']['queries'] == ['Q']


def test_fetch_rss_extracts_and_records_errors(monkeypatch):
    xml = (FIXTURES / 'marketing_recent.xml').read_text()
    def fake_get(url, **kwargs):
        if 'broken' in url:
            raise RuntimeError('feed down')
        return Response(xml)
    monkeypatch.setattr(context, 'safe_get', fake_get)
    result = context.fetch_rss_context([{'id': 'ok', 'name': '营销源', 'url': 'https://x.com/feed'},
                                        {'id': 'bad', 'name': '坏源', 'url': 'https://broken.com/feed'}])
    assert result['errors'] and '坏源' in result['errors'][0]['source']
    assert result['items'] and result['items'][0]['kind'] == 'rss'
    assert result['items'][0]['source'] == '营销源'
    assert result['items'][0]['title'].startswith('微信视频号')
    assert result['items'][0]['snippet']


def test_search_web_records_errors_and_respects_limits(monkeypatch):
    monkeypatch.setattr(context, '_search_ddgs', lambda q, n: [{'title': f'结果 {q}', 'link': f'https://e.org/{q}',
                                                               'source': 'web search', 'kind': 'search',
                                                               'published_at': None, 'snippet': 's', 'query': q}])
    result = context.search_web_context({'enabled': True, 'provider': 'duckduckgo'}, queries=['A', 'B', 'C'], limit=2)
    assert [i['title'] for i in result['items']] == ['结果 A', '结果 B']
    assert context.search_web_context({'enabled': False}, queries=['A']) == {'items': [], 'errors': []}
    monkeypatch.setattr(context, '_search_ddgs', lambda q, n: (_ for _ in ()).throw(ValueError('no provider')))
    failed = context.search_web_context({'enabled': True, 'provider': 'baidu'}, queries=['A'])
    assert failed['items'] == [] and failed['errors'][0]['provider'] == 'baidu'


def test_collect_context_combines_sources(monkeypatch, tmp_path):
    xml = (FIXTURES / 'marketing_recent.xml').read_text()
    monkeypatch.setattr(context, 'safe_get', lambda url, **kw: Response(xml))
    monkeypatch.setattr(context, '_search_ddgs', lambda q, n: [{'title': '搜索结果', 'link': 'https://e.org/s',
                                                               'source': 'web search', 'kind': 'search',
                                                               'published_at': None, 'snippet': 's'}])
    cfg = {'rss': [{'id': 'a', 'name': 'A', 'url': 'https://x.com/feed'}],
           'search': {'enabled': True, 'provider': 'duckduckgo'}}
    items, meta = context.collect_context(cfg, {'brand': 'Sun Life', 'topics': '港险, 分红'})
    assert meta['rss_items'] == 3 and meta['search_items'] == 2
    assert meta['search_queries'] == ['Sun Life 港险', 'Sun Life 分红']
    assert {i['kind'] for i in items} == {'rss', 'search'}
    assert meta['limitations'] and 'not evidence' in meta['limitations'][0]


def test_external_context_reaches_editor_and_is_not_evidence(tmp_path, monkeypatch):
    import insightbot.signal_desk.core as core
    sent = {}
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, **kw):
            sent['body'] = json.loads(kw['json']['messages'][1]['content'])
            class R:
                status_code = 200
                def json(self):
                    return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"headline":"h","avoid":[],"cards":[]}'}}]}
            return R()
    monkeypatch.setenv('SIGNAL_DESK_AI_BASE_URL', 'https://ai.example.org')
    monkeypatch.setenv('SIGNAL_DESK_AI_API_KEY', 'k')
    monkeypatch.setenv('SIGNAL_DESK_AI_MODEL', 'm')
    monkeypatch.setattr(core.httpx, 'Client', Client)
    ctx = [{'title': '行业动态', 'link': 'https://news.example.org/1', 'source': 'A', 'kind': 'rss',
            'published_at': None, 'snippet': '背景说明'}]
    evidence = normalize([{'title': 't', 'url': 'https://e.org/1', 'excerpt': 'not a research finding',
                           'platform': 'test', 'source_id': '1'}], 50)
    core.live_editor({'brand': 'B', 'question': 'Q'}, evidence, tmp_path, {'provider': 'p'}, ctx)
    assert sent['body']['external_context'][0]['title'] == '行业动态'
    assert 'external_context' in core.EDITOR_PROMPT and 'never quote it' in core.EDITOR_PROMPT

    # Context has no evidence id, so it can never be cited as support or quote.
    card = {'title': 'T', 'disposition': 'research', 'observation': 'O', 'interpretation': 'I',
            'brand_relevance': 'R', 'limitations': 'L', 'next_step': 'N', 'evidence_ids': ['https://news.example.org/1'],
            'counter_evidence_ids': []}
    with pytest.raises(ValueError, match='evidence'):
        core.validate_cards([card], evidence)


def test_collect_fetches_context_into_run(tmp_path, monkeypatch):
    import insightbot.signal_desk.core as core
    monkeypatch.setattr(context, 'fetch_rss_context', lambda feeds, **kw: {'items': [
        {'title': '行业动态', 'link': 'https://n.example.org/1', 'source': 'A', 'kind': 'rss', 'published_at': None, 'snippet': 's'}], 'errors': []})
    monkeypatch.setenv('SIGNAL_DESK_CONTEXT_CONFIG', str(_write_cfg(tmp_path)))
    result = Desk(tmp_path / 'state').start('ctx', {'brand': 'B', 'question': 'Q'},
                                           [{'title': 't', 'url': 'https://e.org/1', 'excerpt': 'body text',
                                             'platform': 'test', 'source_id': '1'}], 'demo')
    assert result['external_context'][0]['title'] == '行业动态'
    assert result['coverage']['external_context']['rss_items'] == 1


def _write_cfg(tmp_path):
    path = tmp_path / 'context.json'
    path.write_text(json.dumps({'rss': [{'id': 'a', 'name': 'A', 'url': 'https://x.com/feed'}], 'search': {'enabled': False}}))
    return path
