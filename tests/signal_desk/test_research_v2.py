import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from insightbot.signal_desk import research_v2 as r


BRAND = {'id': 'brand-one', 'name': 'Sun Life', 'source_config': {}}
TASK = {'id': 'task-one', 'request': '理解退休生活里的家庭照护问题'}


def plan(**kwargs):
    return r.create_plan(BRAND, TASK, {'keyword': '退休 照护', **kwargs})


def test_three_methods_and_clarification_boundaries():
    draft = r.create_plan(BRAND, TASK)
    assert draft['ready'] is False and len(draft['questions']) <= 3
    for method in ('content', 'audience'):
        p = plan(task_type=method)
        assert p['ready'] and p['task_type'] == method
        assert any(q['kind'] == 'challenge' for q in p['queries'])
    p = plan(task_type='data_change', budget={'queries': 3})
    assert p['ready'] and len(p['queries']) == 3
    assert p['queries'][0]['keyword'] == p['queries'][1]['keyword']
    assert p['queries'][1]['period'] == 'previous'
    assert p['queries'][1]['end_date'] < p['queries'][0]['start_date']


def test_invalid_budgets_and_vendor_expansion_rejected():
    with pytest.raises(ValueError):
        plan(budget={'queries': 8})
    with pytest.raises(ValueError):
        plan(sources={'justone': True})
    with pytest.raises(ValueError):
        plan(start_date='2026-02-30')
    with pytest.raises(ValueError):
        plan(end_date='2025-01-01', start_date='2026-01-01')


def test_ai_plan_cannot_expand_budget_or_brand():
    def planner(prompt, payload):
        return {'keyword': '退休照护', 'brand_id': 'another-brand', 'budget': {'samples': 900},
                'queries': [{'keyword': '照护经历', 'kind': 'focus'}, {'keyword': '不同经历', 'kind': 'challenge'}], 'questions': []}
    result = r.create_plan(BRAND, TASK, {'budget': {'samples': 12}}, planner=planner)
    assert result['brand_id'] == BRAND['id'] and result['budget']['samples'] == 12
    assert result['planner_mode'] == 'ai'


def test_actual_qiangua_normalized_note_shape_and_missing_url():
    note = {'title': '家庭分工', 'url': 'https://www.xiaohongshu.com/explore/note1',
            'publish_time': '2026-09-01', 'raw': {'NoteId': 'qg123', 'Desc': '照护家人需要全家协商。'}}
    result = r._note(note, {'keyword': '家庭照护'})
    assert result['excerpt'] == '照护家人需要全家协商。'
    assert result['source_grade'] == 'qiangua_body'
    assert r._note({'Title': '没链接'}, {'keyword': 'test'}) is None
    result = r._note({'Title': '标题', 'Url': note['url']}, {'keyword': 'test'})
    assert result['source_grade'] == 'title_only'


class Adapter:
    def __init__(self, fail=False):
        self.searches = []
        self.details = []
        self.fail = fail
    def auth(self):
        return True
    def search(self, query, **kwargs):
        self.searches.append((query, kwargs))
        if self.fail:
            raise r.SourceError('千瓜接口调用失败')
        index = len(self.searches)
        return {'normalized_items': [{'title': f'照护案例{index}', 'url': f'https://www.xiaohongshu.com/explore/n{index}',
                                      'raw': {'NoteId': f'n{index}'}}], 'total_count': 999}
    def detail(self, url):
        self.details.append(url)
        # The actual endpoint can return a normalized note without a URL.
        return {'normalized_note': {'title': '照护个案', 'raw': {'Content': '我和家人协商了退休后的照护分工。'}}}


def test_collection_bounds_body_read_actual_shape_and_cache(tmp_path):
    adapter = Adapter()
    p = plan(budget={'body_reads': 1})
    first = r.collect(p, tmp_path, adapter=adapter)
    assert len(adapter.searches) == 2 and len(adapter.details) == 1
    assert len(first['evidence']) == 2
    assert first['collection']['usable_bodies'] == 1
    assert first['collection']['title_only'] == 1
    assert r.collect(p, tmp_path, adapter=adapter) == first
    assert len(adapter.searches) == 2
    with pytest.raises(ValueError, match='不同计划'):
        r.collect({**p, 'keyword': 'different'}, tmp_path, adapter=adapter)


def test_collection_failures_not_no_signal_and_no_auto_retry(tmp_path):
    adapter = Adapter(fail=True)
    first = r.collect(plan(), tmp_path, adapter=adapter)
    assert first['collection']['status'] == 'failed'
    assert first['collection']['errors']
    assert r.collect(plan(), tmp_path, adapter=adapter)['collection']['status'] == 'failed'
    assert len(adapter.searches) == 2


def test_sources_use_frozen_brand_allowlist_not_global(monkeypatch, tmp_path):
    monkeypatch.setenv('SIGNAL_DESK_CONTEXT_CONFIG', '/should/not/be/read.json')
    captured = []
    def rss(feeds, **kwargs):
        captured.append(feeds)
        return {'items': [], 'errors': []}
    monkeypatch.setattr(r, 'fetch_rss_context', rss)
    brand = {**BRAND, 'source_config': {'rss': True, 'rss_feeds': [{'url': 'https://brand-one.test/feed', 'name': 'One'}]}}
    p = r.create_plan(brand, TASK, {'keyword': '照护'})
    r.collect(p, tmp_path, adapter=Adapter())
    assert captured == [[{'url': 'https://brand-one.test/feed', 'name': 'One'}]]


def test_qiangua_adapter_uses_current_python_and_sanitizes(monkeypatch, tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/qiangua_cli.py').touch()
    captured = []
    def invoke(args, **kwargs):
        captured.append(args)
        return SimpleNamespace(returncode=1, stdout=json.dumps({'status': 'expired', 'msg': 'secret-cookie=abc'}), stderr='sensitive')
    monkeypatch.setattr(r.subprocess, 'run', invoke)
    adapter = r.QianguaAdapter(repo=tmp_path)
    with pytest.raises(r.SourceError) as error:
        adapter.auth()
    assert 'abc' not in str(error.value)
    assert captured[0][0] == r.sys.executable


def test_replanning_comparison_does_not_duplicate_derived_queries():
    first = plan(task_type='data_change', budget={'queries': 3}, start_date='2026-09-01', end_date='2026-09-30')
    second = plan(task_type='data_change', budget={'queries': 3}, queries=first['queries'], start_date='2026-10-01', end_date='2026-10-07')
    assert len(second['queries']) == 3
    prior = next(q for q in second['queries'] if q.get('period') == 'previous')
    assert prior['start_date'] == '2026-09-24' and prior['end_date'] == '2026-09-30'


def test_insufficient_sample_budget_cannot_silently_omit_challenge_query():
    with pytest.raises(ValueError, match='样本预算'):
        plan(budget={'samples': 1})


def test_default_qiangua_checkout_is_sibling_of_product(monkeypatch):
    monkeypatch.delenv('SIGNAL_DESK_QIANGUA_REPO', raising=False)
    expected = Path(r.__file__).resolve().parents[2].parent / 'qiangua-insights'
    assert r.QianguaAdapter().repo == expected
