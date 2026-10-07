import copy
from pathlib import Path

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="Install requirements-signal-desk.txt for the isolated Signal Desk runtime")

from insightbot.signal_desk import editorial_v2 as e
from insightbot.signal_desk.research_v2 import create_plan


EVIDENCE = [{'id': 'E1', 'title': '家庭分工', 'url': 'https://example.com/note1', 'excerpt': '我与家人协商了退休之后的照护分工。', 'source_grade': 'qiangua_body'}]
TEXT = '''CANDIDATE|C01|select|照护分工影响退休安排|E1|-|补充家庭分工的理解
CARD|C01|signal|退休安排还受照护分工影响|个案中，作者把照护家人的责任纳入退休安排。|讨论退休生活时，可将家庭分工纳入问题清单。|单个自述，不能代表目标人群。|现有问题清单是否覆盖了谁照护谁？|E1|-
CHECK|C01|yes|yes|yes|yes|yes|yes
SCOPE|限定主题下的千瓜个案；外部语境尚未核验。'''


def parsed():
    return e.parse_protocol(TEXT)


def test_valid_card_protocol_and_markdown_never_exports_candidate_reason():
    result = parsed()
    assert e.validate_edition(result, EVIDENCE) == []
    md = e.render_markdown(result, EVIDENCE, 'Sun Life')
    assert '[家庭分工](https://example.com/note1)' in md
    assert '补充家庭分工的理解' not in md and 'CHECK' not in md


def test_twelve_candidates_only_selected_three_and_zero_valid():
    result = parsed()
    for index in range(2, 13):
        result['candidates'].append({'id': f'C{index:02}', 'title': '其他材料', 'reason': '重复已知理解', 'disposition': 'drop', 'evidence_ids': ['E1'], 'counter_evidence_ids': []})
    assert len(result['candidates']) == 12 and len(result['cards']) == 1
    assert not e.validate_edition(result, EVIDENCE)
    result['cards'] = []
    result['candidates'][0]['disposition'] = 'observe'
    assert not e.validate_edition(result, EVIDENCE)


def test_more_than_three_and_overlong_not_truncated():
    result = parsed()
    result['cards'] *= 4
    assert any('数量' in x for x in e.validate_edition(result, EVIDENCE))
    result = parsed()
    result['cards'][0]['observation'] = '长' * 121
    before = copy.deepcopy(result)
    assert any('超字数' in x for x in e.validate_edition(result, EVIDENCE))
    assert result == before


def test_unknown_source_overlap_title_only_and_same_origin_not_trend():
    result = parsed()
    result['cards'][0]['counter_evidence_ids'] = ['E1']
    assert any('重叠' in x for x in e.validate_edition(result, EVIDENCE))
    result['cards'][0]['counter_evidence_ids'] = ['invented']
    assert any('未知' in x for x in e.validate_edition(result, EVIDENCE))
    result = parsed()
    assert any('仅有标题' in x for x in e.validate_edition(result, [{**EVIDENCE[0], 'source_grade': 'title_only'}]))
    result['cards'][0]['claim_type'] = 'trend'
    assert any('时间序列' in x for x in e.validate_edition(result, EVIDENCE))
    result['cards'][0]['time_series'] = {'metric': 'invented'}
    assert any('时间序列' in x for x in e.validate_edition(result, EVIDENCE))


def test_duplicate_history_and_numeric_prescription_rejected():
    result = parsed()
    prior = [{'id': 'edition-one', 'delivery': copy.deepcopy(result)}]
    assert any('重复' in x for x in e.validate_edition(result, EVIDENCE, previous_editions=prior))
    result['cards'][0]['brand_reference'] = '建议将30%预算转到照护主题。'
    assert any('执行指令' in x for x in e.validate_edition(result, EVIDENCE))
    result = parsed()
    result['cards'][0]['brand_reference'] = '持续优化'
    assert any('空泛' in x for x in e.validate_edition(result, EVIDENCE))


def test_numeric_substring_cannot_become_grounded_fact():
    result = parsed()
    result['cards'][0]['observation'] = '作者称照护安排持续了30天。'
    evidence = [{**EVIDENCE[0], 'excerpt': '我已照护家人130天。'}]
    assert any('数字' in x for x in e.validate_edition(result, evidence))


def test_lookback_requires_new_evidence_and_existing_edition():
    result = parsed()
    result['lookback'] = {'previous_id': 'previous', 'text': '新个案补充了家庭分工的差异。', 'evidence_ids': ['E1']}
    assert any('历史交付' in x for x in e.validate_edition(result, EVIDENCE))
    previous = [{'id': 'previous', 'evidence': EVIDENCE, 'delivery': {'cards': []}}]
    assert any('没有新证据' in x for x in e.validate_edition(result, EVIDENCE, previous_editions=previous))
    previous[0]['evidence'] = []
    assert not e.validate_edition(result, EVIDENCE, previous_editions=previous)


def test_rewrite_is_bounded_and_never_truncates(tmp_path):
    plan = create_plan({'id': 'brand1'}, {'id': 'task1', 'request': '家庭照护'}, {'keyword': '退休照护'})
    collected = {'evidence': EVIDENCE, 'collection': {'status': 'complete'}}
    calls = []
    def editor(prompt, payload):
        calls.append(payload)
        return TEXT.replace('退休安排还受照护分工影响', '长' * 27) if len(calls) == 1 else TEXT
    result = e.edit(plan, collected, run_dir=tmp_path, editor=editor)
    assert len(calls) == 2
    assert result['cards'][0]['title'] == '退休安排还受照护分工影响'
    assert 'validation_errors' in calls[1]
    plan['budget']['model_calls'] = 1
    with pytest.raises(ValueError, match='未截断'):
        e.edit(plan, collected, run_dir=tmp_path / 'second', editor=lambda *_: 'invalid')


def test_no_evidence_no_paid_call_but_failed_sources_not_zero(tmp_path):
    plan = create_plan({'id': 'brand1'}, {'request': '照护'}, {'keyword': '照护'})
    def should_not_call(*args):
        raise AssertionError('must not pay')
    result = e.edit(plan, {'evidence': [], 'collection': {'status': 'empty'}}, run_dir=tmp_path, editor=should_not_call)
    assert not result['cards'] and not result['model_usage']
    with pytest.raises(ValueError, match='采集失败'):
        e.edit(plan, {'evidence': [], 'collection': {'status': 'failed'}}, run_dir=tmp_path / 'failed', editor=should_not_call)


def test_total_body_cap_includes_lookback_and_scope():
    result = {'cards': [], 'candidates': [], 'lookback': {'previous_id': 'old', 'text': '回' * 120, 'evidence_ids': ['E1']}, 'scope': '范' * 100}
    for index in range(3):
        cid = f'C{index+1:02}'
        result['candidates'].append({'id': cid, 'disposition': 'select', 'title': '候选', 'reason': '取舍', 'evidence_ids': ['E1'], 'counter_evidence_ids': []})
        result['cards'].append({'candidate_id': cid, 'claim_type': 'signal', 'title': chr(0x4e00+index)*20, 'observation': '观'*120,
                               'brand_reference': '参'*60, 'boundary': '界'*40, 'question': '问'*40, 'evidence_ids': ['E1'], 'counter_evidence_ids': [],
                               'quality_checks': {k: 'yes' for k in ('sources','grounded','relevant','specific','non_prescriptive','new')}})
    errors = e.validate_edition(result, EVIDENCE, previous_editions=[{'id': 'old', 'evidence': [], 'delivery': {'cards': []}}])
    assert errors == ['整期正文超过字数上限']


def test_model_excerpt_budget_preserves_originals_and_newest_history():
    originals = [{**EVIDENCE[0], 'id': f'E{i}', 'excerpt': '原' * 12000} for i in range(60)]
    previous = [{'id': str(i), 'delivery': {'cards': []}} for i in range(8)]
    payload = e._editor_input({}, {'evidence': originals}, previous)
    assert sum(len(item['excerpt']) for item in payload['evidence']) <= 48000
    assert all(len(item['excerpt']) == 12000 for item in originals)
    assert [row['id'] for row in payload['previous_editions']] == ['0', '1', '2', '3']
