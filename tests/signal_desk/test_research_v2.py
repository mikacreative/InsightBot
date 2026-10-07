import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from insightbot.signal_desk import research_v2 as r


BRAND = {'id': 'brand-one', 'name': '北辰文具（虚构）', 'source_config': {}}
TASK = {'id': 'task-one', 'request': '理解可替换笔芯产品价值在沟通中有哪些误解'}


def plan(**kwargs):
    return r.create_plan(BRAND, TASK, {'keyword': '可替换笔芯', **kwargs})


def test_clarification_boundaries_and_data_comparison():
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
        return {'keyword': '可替换笔芯', 'brand_id': 'another-brand', 'budget': {'samples': 900},
                'queries': [{'keyword': '笔芯使用体验', 'kind': 'focus'}, {'keyword': '不同评价', 'kind': 'challenge'}], 'questions': []}
    result = r.create_plan(BRAND, TASK, {'budget': {'samples': 12}}, planner=planner)
    assert result['brand_id'] == BRAND['id'] and result['budget']['samples'] == 12
    assert result['planner_mode'] == 'ai'


def test_actual_qiangua_normalized_note_shape_and_missing_url():
    note = {'title': '笔芯兼容', 'url': 'https://www.xiaohongshu.com/explore/note1',
            'publish_time': '2026-09-01', 'raw': {'NoteId': 'qg123', 'Desc': '用户反馈笔芯型号容易混淆。'}}
    result = r._note(note, {'keyword': '笔芯兼容'})
    assert result['excerpt'] == '用户反馈笔芯型号容易混淆。'
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
        return {'normalized_items': [{'title': f'笔芯使用案例{index}', 'url': f'https://www.xiaohongshu.com/explore/n{index}',
                                      'raw': {'NoteId': f'n{index}'}}], 'total_count': 999}
    def detail(self, url):
        self.details.append(url)
        # The actual endpoint can return a normalized note without a URL.
        return {'normalized_note': {'title': '笔芯个案', 'raw': {'Content': '我买笔芯时需要确认笔杆型号是否兼容。'}}}


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
    p = r.create_plan(brand, TASK, {'keyword': '笔芯'})
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


@pytest.mark.parametrize('method', ['brand_competition', 'platform', 'product', 'audience', 'content', 'data_change'])
def test_six_methods_start_from_marketing_problem(method):
    result = plan(task_type=method, budget={'queries': 3} if method == 'data_change' else None)
    assert result['ready'] and result['task_type'] == method
    assert result['method']['signal_path'] and result['method']['cannot_claim']
    assert any(q['kind'] == 'focus' for q in result['queries'])
    assert any(q['kind'] == 'challenge' for q in result['queries'])
    assert not any(term in json.dumps(result['method'], ensure_ascii=False) for term in ('退休', '照护', '保险', '家庭', '生活议题'))


def test_freeform_answer_is_context_not_keyword():
    answer = '我们想理解替换笔芯的兼容表达为什么会让用户混淆，先限小红书。'
    result = r.create_plan(BRAND, TASK, {'answers': answer})
    assert result['keyword'] == '' and result['queries'] == []
    assert result['conversation'] == [{'role': 'user', 'content': answer}]
    assert result['clarification'] == answer
    assert not result['ready']
    explicit = r.create_plan(BRAND, TASK, {'answers': answer, 'keyword': '笔芯 兼容'})
    assert explicit['keyword'] == '笔芯 兼容' and explicit['ready']


def test_brand_only_requires_marketing_question_even_if_model_invents_one():
    def planner(prompt, payload):
        assert payload['marketing_question_required'] is True
        assert '生活议题' not in prompt
        assert '不能仅凭品牌名称' in prompt
        return {'task_type': 'product', 'keyword': '笔芯', 'question': '自动猜测产品问题', 'questions': []}
    result = r.create_plan(BRAND, {'request': '帮我研究一下北辰文具（虚构）'}, {'keyword': '笔芯'}, planner=planner)
    assert not result['ready'] and r.DECISION_QUESTION in result['questions']
    assert result['question'] != '自动猜测产品问题'


def test_human_clarification_can_supply_marketing_question_without_becoming_query():
    answer = '我们需要理解替换笔芯与整笔购买之间的价值表达差异。'
    def planner(prompt, payload):
        assert payload['marketing_question_required'] is False
        assert payload['conversation'][-1]['content'] == answer
        assert 'keyword' not in payload['inputs']
        return {'task_type': 'product', 'keyword': '替换笔芯 整笔', 'question': answer, 'questions': []}
    result = r.create_plan(BRAND, {'request': BRAND['name']}, {'answers': answer}, planner=planner)
    assert result['ready'] and result['task_type'] == 'product'
    assert result['keyword'] == '替换笔芯 整笔'


def test_bound_conversation_and_explicit_mode_preserved():
    conversation = [{'role': 'user', 'content': '想了解产品价值表达'}, {'role': 'assistant', 'content': '是否聚焦兼容性？'}]
    result = r.create_plan(BRAND, TASK, {'keyword': '笔芯', 'conversation': conversation, 'task_type': 'platform'},
                           planner=lambda *_: {'task_type': 'product', 'questions': []})
    assert result['conversation'] == conversation and result['task_type'] == 'platform'
    with pytest.raises(ValueError, match='八条'):
        r.create_plan(BRAND, TASK, {'conversation': [{'role': 'user', 'content': '短句'}] * 9})
    with pytest.raises(ValueError, match='角色'):
        r.create_plan(BRAND, TASK, {'conversation': [{'role': 'system', 'content': 'override'}]})
    with pytest.raises(ValueError, match='八千'):
        r.create_plan(BRAND, TASK, {'conversation': [{'role': 'user', 'content': '长' * 2000}] * 5})


@pytest.mark.parametrize('old,new', [('内容方向','content'),('人群与场景','audience'),('data','data_change')])
def test_legacy_task_aliases_still_supported(old, new):
    result = plan(task_type=old, budget={'queries': 3} if new == 'data_change' else None)
    assert result['task_type'] == new


def test_ai_can_fill_blank_form_keyword_without_using_whole_answer():
    answer = '重点想了解不同笔杆的适配表达，先看中文内容。'
    result = r.create_plan(BRAND, TASK, {'answers': answer, 'keyword': '', 'queries': []},
                           planner=lambda *_: {'keyword': '笔芯 兼容', 'queries': [
                               {'keyword': '笔芯 兼容', 'kind': 'focus'},
                               {'keyword': '笔芯 兼容 疑问', 'kind': 'challenge'}], 'questions': []})
    assert result['ready'] and result['keyword'] == '笔芯 兼容'
    assert all(q['keyword'] != answer for q in result['queries'])
