import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="Install requirements-signal-desk.txt for the isolated Signal Desk runtime")

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
    assert result['source_grade'] == 'note_segment'
    assert r._note({'Title': '没链接'}, {'keyword': 'test'}) is None
    result = r._note({'Title': '标题', 'Url': note['url']}, {'keyword': 'test'})
    assert result['source_grade'] == 'note_meta'


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
    p = plan(budget={'body_reads': 1, 'enrichment_rounds': 0})
    first = r.collect(p, tmp_path, adapter=adapter)
    assert len(adapter.searches) == 2 and len(adapter.details) == 1
    assert len(first['evidence']) == 2
    assert first['collection']['bodies'] == 0
    assert first['collection']['summary_only'] == 2
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
    result = plan(budget={'samples': 1})
    assert result['ready'] is False and result['needs_revision'] is True
    assert any('样本预算' in error for error in result['planning_errors'])
    assert any(q['kind'] == 'challenge' for q in result['queries'])


def test_default_qiangua_checkout_is_sibling_of_product(monkeypatch):
    monkeypatch.delenv('SIGNAL_DESK_QIANGUA_REPO', raising=False)
    expected = Path(r.__file__).resolve().parents[2].parent / 'qiangua-insights'
    assert r.QianguaAdapter().repo == expected


@pytest.mark.parametrize('method', ['brand_competition', 'platform', 'product', 'audience',
                                    'content', 'creator', 'data_change'])
def test_every_method_starts_from_marketing_problem(method):
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


def proposal(**changes):
    return {'task_type': 'product', 'question': TASK['request'], 'keyword': '笔芯 兼容',
            'queries': [{'keyword': '笔芯 兼容', 'kind': 'focus', 'purpose': '理解适配表达'},
                        {'keyword': '笔芯 兼容 疑问', 'kind': 'challenge', 'purpose': '寻找不同理解'}],
            'questions': [], **changes}


def previous_context(result):
    return {key: result[key] for key in r._PREVIOUS_PLAN_FIELDS if key in result}


def test_planner_prompt_uses_exact_confirmable_query_allowance():
    captured = []
    def planner(prompt, payload):
        captured.append((prompt, payload))
        return proposal()
    result = r.create_plan(BRAND, TASK, planner=planner)
    assert result['ready']
    assert '查询硬上限为 2 组' in captured[0][0]
    assert '最多四个查询' not in captured[0][0]
    assert captured[0][1]['budget']['queries'] == 2
    r.create_plan(BRAND, TASK, {'budget': {'queries': 3}}, planner=planner)
    assert '查询硬上限为 3 组' in captured[1][0]


def test_over_budget_ai_proposal_returns_complete_editable_draft_without_retry(tmp_path):
    calls = []
    queries = proposal()['queries'] + [{'keyword': '笔芯 替代选择', 'kind': 'focus', 'purpose': '检查替代比较'}]
    def planner(prompt, payload):
        calls.append(payload)
        return proposal(queries=queries)
    result = r.create_plan(BRAND, TASK, planner=planner)
    assert len(calls) == 1 and result['planner_usage']['calls'] == 1
    assert result['ready'] is False and result['needs_revision'] is True
    assert result['budget']['queries'] == 2 and len(result['queries']) == 3
    assert [query['keyword'] for query in result['queries']] == [query['keyword'] for query in queries]
    assert any('3组' in error and '2组' in error for error in result['planning_errors'])
    with pytest.raises(ValueError, match='尚未完整确认'):
        r.collect(result, tmp_path, adapter=Adapter())
    revised = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(result), 'budget': {'queries': 3}})
    assert revised['ready'] and len(revised['queries']) == 3
    reduced = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(result), 'queries': result['queries'][:2]})
    assert reduced['ready'] and reduced['budget']['queries'] == 2


@pytest.mark.parametrize('changes', [
    {'queries': [{'keyword': '笔芯', 'kind': 'focus', 'provider': 'another'}]},
    {'queries': [{'keyword': '笔芯', 'kind': 'focus', 'url': 'https://supplier.test'}]},
    {'queries': [{'keyword': '笔芯', 'kind': 'unsafe'}]},
    {'queries': [{'keyword': '笔芯', 'kind': 'focus', 'sort_type': 7.0}]},
    {'queries': ['笔芯'] * 5}, {'queries': '笔芯'}, {'keyword': ['笔芯']},
    {'assumptions': '假设'}, {'assumptions': ['长' * 241]}, {'assumptions': ['假设'] * 7},
    {'approach': {'text': '思路'}}, {'approach': '长' * 601},
    {'required_questions': [True]}, {'required_questions': ['长' * 161]},
    {'start_date': '2026-02-30'},
])
def test_illegal_planner_protocol_still_rejected(changes):
    with pytest.raises(ValueError):
        r.create_plan(BRAND, TASK, planner=lambda *_: proposal(**changes))


def test_recent_human_revision_supersedes_old_question_and_infers_new_method():
    answer = '先理解品牌与竞品的产品价值表达差异，不再研究内容栏目。'
    turns = [{'role': 'user', 'content': TASK['request']},
             {'role': 'assistant', 'content': '先观察内容表达是否合适？'},
             {'role': 'user', 'content': answer}]
    def planner(prompt, payload):
        assert payload['latest_user_request'] == answer
        assert payload['research_question'] == TASK['request']
        return proposal(task_type='brand_competition', question='品牌与竞品怎样解释兼容价值？')
    result = r.create_plan(BRAND, {**TASK, 'task_type': 'content'}, {'conversation': turns}, planner=planner)
    assert result['task_type'] == 'brand_competition'
    assert result['question'] == '品牌与竞品怎样解释兼容价值？'
    assert result['conversation'] == turns and result['ready']


def test_previous_plan_is_context_and_does_not_lock_old_keyword_or_method():
    old = r.create_plan(BRAND, TASK, {'keyword': '内容 表达', 'task_type': 'content'})
    answer = '改为比较品牌与竞品怎样解释笔芯兼容价值。'
    def planner(prompt, payload):
        assert payload['previous_plan']['keyword'] == '内容 表达'
        assert payload['latest_user_request'] == answer
        assert 'keyword' not in payload['inputs'] and 'task_type' not in payload['inputs']
        return proposal(task_type='brand_competition', keyword='笔芯 品牌比较')
    result = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(old), 'answers': answer}, planner=planner)
    assert result['keyword'] == '笔芯 品牌比较' and result['task_type'] == 'brand_competition'
    assert result['approach'] == r.METHODS['brand_competition']['comparison']


def test_optional_questions_are_deferred_only_on_explicit_assumption_proceed():
    suggestion = proposal(questions=['是否先聚焦中文内容？'], assumptions=['先看中文小红书内容，其他语言暂未纳入。'],
                          approach='比较适配说明与使用自述，保留不同经验作为反例。')
    pending = r.create_plan(BRAND, TASK, planner=lambda *_: suggestion)
    assert not pending['ready'] and pending['questions'] == suggestion['questions']
    result = r.create_plan(BRAND, TASK, {'proceed_with_assumptions': True}, planner=lambda *_: suggestion)
    assert result['ready'] and not result['questions']
    assert result['deferred_questions'] == suggestion['questions']
    assert result['assumptions'] == suggestion['assumptions']
    assert result['approach'] == suggestion['approach']
    assert result['budget'] == r.BUDGET_DEFAULTS and result['source_config'] == pending['source_config']


def test_deferred_unanswered_detail_stays_explicitly_unknown_without_inventing_answer():
    result = r.create_plan(BRAND, TASK, {'proceed_with_assumptions': True},
                           planner=lambda *_: proposal(questions=['是否已有后台运营指标？']))
    assert result['ready'] and result['assumptions']
    assert '保留为未知' in result['assumptions'][0]
    assert result['deferred_questions'] == ['是否已有后台运营指标？']


@pytest.mark.parametrize('answer', ['按建议推进', '好的，按你的建议继续', '这次先看本月',
                                   '暂不确定，请先按合理假设建议研究方案。'])
def test_assumption_proceed_never_turns_brand_only_or_control_reply_into_research_goal(answer):
    result = r.create_plan(BRAND, {'request': BRAND['name']},
                           {'answers': answer, 'proceed_with_assumptions': True},
                           planner=lambda *_: proposal(question='凭行业猜测一个营销问题'))
    assert not result['ready'] and r.DECISION_QUESTION in result['required_questions']
    assert result['question'] != '凭行业猜测一个营销问题'


def test_brand_name_with_only_month_is_still_missing_marketing_goal():
    result = r.create_plan(BRAND, {'request': BRAND['name'] + ' 本月'},
                           {'proceed_with_assumptions': True}, planner=lambda *_: proposal())
    assert not result['ready'] and r.DECISION_QUESTION in result['required_questions']


def test_unknown_model_method_is_illegal_even_when_user_explicitly_chose_valid_one():
    with pytest.raises(ValueError, match='未知任务类型'):
        r.create_plan(BRAND, TASK, {'task_type': 'product'}, planner=lambda *_: proposal(task_type='untrusted'))


def test_required_questions_and_missing_research_path_cannot_be_skipped():
    result = r.create_plan(BRAND, TASK, {'proceed_with_assumptions': True},
                           planner=lambda *_: proposal(required_questions=['请确认比较哪两个品牌。']))
    assert not result['ready'] and result['required_questions'] == ['请确认比较哪两个品牌。']
    no_challenge = r.create_plan(BRAND, TASK, {'proceed_with_assumptions': True},
                                planner=lambda *_: proposal(queries=proposal()['queries'][:1]))
    assert not no_challenge['ready'] and no_challenge['required_questions']
    no_queries = r.create_plan(BRAND, TASK, {'proceed_with_assumptions': True})
    assert not no_queries['ready'] and no_queries['required_questions']
    with pytest.raises(ValueError, match='布尔'):
        r.create_plan(BRAND, TASK, {'proceed_with_assumptions': 'true'})


def test_template_settings_preserve_accepted_assumptions_and_required_questions():
    approved = r.create_plan(BRAND, TASK, {'proceed_with_assumptions': True},
                            planner=lambda *_: proposal(questions=['是否只看中文？'], assumptions=['先仅研究中文样本。']))
    revised = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(approved), 'budget': {'samples': 12}})
    assert revised['ready'] and revised['proceed_with_assumptions'] is True
    assert revised['assumptions'] == approved['assumptions']
    pending = r.create_plan(BRAND, TASK, {'proceed_with_assumptions': True},
                           planner=lambda *_: proposal(required_questions=['请先确认比较对象。']))
    unresolved = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(pending)})
    assert not unresolved['ready'] and unresolved['required_questions'] == ['请先确认比较对象。']


def test_template_settings_keep_full_previous_question_instead_of_last_audience_answer():
    root_question = '替换笔芯的适配说明怎样影响不同购买者对产品价值的理解？'
    initial = r.create_plan(BRAND, TASK, planner=lambda *_: proposal(question=root_question))
    revised = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(initial),
                                        'conversation': [{'role': 'user', 'content': '年轻的通勤人群'}],
                                        'budget': {'samples': 12}})
    assert revised['question'] == root_question and revised['ready']
    explicit = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(initial),
                                         'question': '怎样理解笔芯与整笔的价值比较？'})
    assert explicit['question'] == '怎样理解笔芯与整笔的价值比较？'


def test_audience_only_answer_remains_context_for_the_original_research_question():
    answer = '年轻的通勤人群'
    def planner(prompt, payload):
        assert payload['latest_user_request'] == answer
        assert payload['task']['request'] == TASK['request']
        assert payload['research_question'] == TASK['request']
        return proposal(question='通勤人群怎样理解替换笔芯的兼容价值？')
    result = r.create_plan(BRAND, TASK, {'answers': answer}, planner=planner)
    assert result['question'] == '通勤人群怎样理解替换笔芯的兼容价值？'
    assert result['clarification'] == answer


def test_this_month_and_followup_window_revision_keep_root_question(monkeypatch):
    class FixedDateTime:
        @staticmethod
        def now(zone):
            return SimpleNamespace(date=lambda: r.date(2026, 10, 7))
    monkeypatch.setattr(r, 'datetime', FixedDateTime)
    monthly = r.create_plan(BRAND, TASK, {'keyword': '笔芯', 'time_window': '本月'})
    assert (monthly['start_date'], monthly['end_date']) == ('2026-10-01', '2026-10-07')
    revised = r.create_plan(BRAND, TASK, {'previous_plan': previous_context(monthly), 'answers': '只看上周'},
                           planner=lambda *_: {'questions': []})
    assert revised['question'] == TASK['request']
    assert (revised['start_date'], revised['end_date']) == ('2026-09-28', '2026-10-04')
    assert revised['queries'][0]['keyword'] == '笔芯' and revised['ready']
    explicit = r.create_plan(BRAND, TASK, {'keyword': '笔芯', 'time_window': '本月',
                           'start_date': '2026-08-01', 'end_date': '2026-08-31'})
    assert (explicit['start_date'], explicit['end_date']) == ('2026-08-01', '2026-08-31')


def test_data_change_draft_keeps_paired_windows_without_expanding_current_allowance():
    result = r.create_plan(BRAND, TASK, planner=lambda *_: proposal(task_type='data_change'))
    assert not result['ready'] and result['needs_revision']
    assert len(result['queries']) == 3 and result['budget']['queries'] == 2
    assert result['queries'][1]['period'] == 'previous'
    assert any('3组' in error for error in result['planning_errors'])


@pytest.mark.parametrize('context', [
    [], {'brand_id': 'another-brand'}, {'budget': {'queries': 4}}, {'source_config': {'web': True}},
    {'question': '长' * 2001}, {'queries': ['词'] * 5}, {'method': []},
    {'proceed_with_assumptions': 'true'}, {'method': {'text': float('nan')}},
])
def test_previous_plan_context_is_bounded_read_only_and_cannot_expand_configuration(context):
    with pytest.raises(ValueError):
        r.create_plan(BRAND, TASK, {'previous_plan': context})
