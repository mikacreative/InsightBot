"""The L3／T structure tier: reader, plan freeze, and the provenance rule it lands on.

Shapes were confirmed against real 2026-10-12 capability responses through the 千瓜 CLI:

* ``brand.search``              -> ``result.normalized_items[{brand_id, brand_id_key, name}]``
* ``brand.get_sov_chart``       -> ``result.items[{DateCode, DateStr, NoteCountPercent, ...}]``
* ``brand.get_blogger_pyramid`` -> ``result.items[{PropName, BlogeerCount, BloggerProportion}]``
* ``keyword.note_trends``       -> ``result.day_list[{Date, DateStr, NoteCount, HeatValue}]``

``category.funnel`` / ``category.trends`` / ``category.overview`` accept a ``tag_id`` but the
upstream answers 500 品类传参有误 or an all-zero payload for every tag id ``tag.list`` returns,
so they are deliberately **not** registered — see ``STRUCTURE_READS``. Wiring a read on a guess
is how a pipeline starts reporting zeros as measurements.

Three properties matter beyond "it parses":

1. These reads cost no money. 千瓜 bills by the seat, so they must not pass through the spend
   gate, which exists for a per-call vendor. A count of calls is frozen instead.
2. ``probe`` must still derive exactly ``BUDGET_DEFAULTS``. It declares neither L3 nor T, so
   its structure allowance is zero by construction rather than by a special case.
3. An aggregate has no page. The editorial rule that demands a URL from note text had to be
   able to say what it demands instead, or L3／T evidence could never support anything.
"""
from decimal import Decimal

import pytest

from insightbot.signal_desk import costcontrol as c, editorial_v2 as e, grades, research_v2 as r

BRAND = {'id': 'fictional-brand', 'name': '虚构品牌'}
TASK = {'id': 'task1', 'request': '看我们在品类的合作结构里处在什么位置'}

SOV_ROWS = [{'DateCode': 20260913, 'DateStr': '09.13', 'NoteCount': 650, 'NoteCountPercent': 0.0009},
            {'DateCode': 20260914, 'DateStr': '09.14', 'NoteCount': 771, 'NoteCountPercent': 0.001}]
PYRAMID_ROWS = [{'Prop': 4, 'PropName': '知名KOL', 'BlogeerCount': 15, 'BloggerProportion': 0.0012},
                {'Prop': 64, 'PropName': '头部达人', 'BlogeerCount': 71, 'BloggerProportion': 0.0057}]
TREND_ROWS = [{'Date': 20260901, 'DateStr': '09.01', 'NoteCount': 5936, 'HeatValue': 8758},
              {'Date': 20260902, 'DateStr': '09.02', 'NoteCount': 6102, 'HeatValue': 9100}]


class FakeAdapter:
    """Stands in for the 千瓜 CLI: brand resolution plus one capability call per read."""

    configured = True

    def __init__(self, brand_failure=None, bad_shape=(), empty=()):
        self.brand_failure = brand_failure
        self.bad_shape, self.empty = set(bad_shape), set(empty)
        self.calls, self.brand_names = [], []

    def auth(self):
        return True

    def brand(self, name):
        self.brand_names.append(name)
        if self.brand_failure is not None:
            raise self.brand_failure
        return {'id': 31505, 'key': '77f3e7', 'name': name}

    def capability(self, name, inputs):
        self.calls.append((name, dict(inputs)))
        if name in self.bad_shape:
            return {'unexpected': 'shape'}
        if name == 'brand.get_sov_chart':
            return {'items': list(SOV_ROWS)}
        if name == 'brand.get_blogger_pyramid':
            return {'items': list(PYRAMID_ROWS)}
        return {'day_list': [] if name in self.empty else list(TREND_ROWS)}


def plan(**inputs):
    return r.create_plan(BRAND, TASK, {'keyword': '口红', **inputs})


def read_of(item):
    return item['source']['read']


def test_every_registered_read_declares_a_real_layer_and_a_real_grade():
    """The registry is the single place a read is declared, so it is the place to check."""
    for read, definition in r.STRUCTURE_READS.items():
        assert definition['layer'] in r.LAYERS, read
        assert definition['needs'] in ('brand', 'keyword'), read
        assert definition['capability'] and definition['label'] and definition['limitation'], read
        # grades.py owns what a grade means; a typo here would resolve to unverified
        # (rank 0, summary-only) and quietly demote the whole read.
        assert grades.level(definition['grade']) == definition['grade'], read
        assert not grades.is_note_text(definition['grade']), read


def test_no_read_is_registered_for_a_capability_whose_shape_was_never_confirmed():
    """The category reads stay out until the category id's source is settled."""
    registered = {definition['capability'] for definition in r.STRUCTURE_READS.values()}
    assert not any(name.startswith('category.') for name in registered)


def test_the_default_mode_asks_for_no_structure_reads():
    """The invariant that keeps a caller who names no mode from changing behaviour."""
    assert r.mode_structure_reads('probe') == ()
    assert r.mode_budget('probe')['structure_reads'] == r.BUDGET_DEFAULTS['structure_reads'] == 0


def test_a_mode_asks_for_exactly_the_layers_it_declares():
    assert r.mode_structure_reads('scan') == ('keyword_trend',)
    assert r.mode_structure_reads('frame') == ('brand_sov', 'brand_pyramid', 'keyword_trend')
    assert r.mode_budget('frame')['structure_reads'] == len(r.STRUCTURE_READS)


def test_the_two_layers_that_were_dark_are_now_reachable():
    gaps = {gap['task_type']: gap['missing_primary'] for gap in r.layer_gaps()}
    assert 'brand_competition' not in gaps and 'data_change' not in gaps
    # L2 and L4 keep their readers unwritten; shrinking the gap list must not hide them.
    assert gaps == {'audience': ['L2'], 'creator': ['L2'], 'product': ['L4']}


def test_the_plan_freezes_the_reads_and_an_operator_can_only_lower_them():
    frame = plan(mode='frame')
    assert frame['structure'] == ['brand_sov', 'brand_pyramid', 'keyword_trend']
    assert frame['budget']['structure_reads'] == 3
    lowered = plan(mode='frame', budget={'structure_reads': 1})
    # Truncated rather than merely checked: intent and ceiling cannot disagree.
    assert lowered['structure'] == ['brand_sov'] and lowered['budget']['structure_reads'] == 1
    assert plan(mode='probe')['structure'] == []


def test_survey_files_the_reads_it_was_told_to_make(tmp_path):
    outcome = r.survey(plan(mode='frame'), tmp_path, adapter=FakeAdapter())
    assert outcome['reads'] == ['brand_sov', 'brand_pyramid', 'keyword_trend']
    assert [item['source_grade'] for item in outcome['structure']] == \
        ['brand_structure', 'brand_structure', 'trend_series']
    assert [item['id'] for item in outcome['structure']] == ['S1', 'S2', 'S3']
    assert outcome['collection']['status'] == 'complete'
    assert outcome['collection']['layers'] == ['L3', 'T']
    assert outcome['collection']['grades'] == {'brand_structure': 2, 'trend_series': 1}


def test_a_structure_read_states_its_provenance_instead_of_a_page(tmp_path):
    frame = plan(mode='frame')
    item = r.survey(frame, tmp_path, adapter=FakeAdapter())['structure'][0]
    assert item['url'] == ''
    assert item['source']['vendor'] == 'qiangua'
    assert item['source']['capability'] == 'brand.get_sov_chart'
    assert item['source']['window'] == {'start_date': frame['start_date'], 'end_date': frame['end_date']}
    assert item['source']['rows'] == len(SOV_ROWS)


def test_the_series_are_emitted_in_the_shape_the_editorial_guard_reads(tmp_path):
    """``_trend_supported`` is the interface this material was always meant to fill."""
    items = r.survey(plan(mode='frame'), tmp_path, adapter=FakeAdapter())['structure']
    trend = next(item for item in items if item['source_grade'] == 'trend_series')
    assert trend['time_series']['metric'] and trend['time_series']['unit']
    assert trend['time_series']['coverage'] and trend['time_series']['source']
    assert e._trend_supported([trend]) is True
    # SOV is a dated ratio, so it can carry the same claim a keyword series can.
    sov = next(item for item in items if read_of(item) == 'brand_sov')
    assert e._trend_supported([sov]) is True


def test_the_series_is_anchored_to_the_plan_window_not_to_today(tmp_path):
    """Two series are only comparable if they cover the same dates."""
    adapter = FakeAdapter()
    frame = plan(mode='frame')
    r.survey(frame, tmp_path, adapter=adapter)
    inputs = dict(adapter.calls)['keyword.note_trends']
    assert inputs['start_time'] == frame['start_date'] and inputs['end_time'] == frame['end_date']
    assert inputs['keyword'] == frame['keyword']
    brand_inputs = dict(adapter.calls)['brand.get_sov_chart']
    assert brand_inputs['brand_id'] == 31505 and brand_inputs['brand_id_key'] == '77f3e7'


def test_a_structure_read_is_never_gated_by_costcontrol(tmp_path):
    """千瓜 bills by the seat, so a per-call envelope is the wrong instrument entirely."""
    import inspect

    parameters = inspect.signature(r.survey).parameters
    assert 'envelope' not in parameters and 'spend_ledger' not in parameters
    r.survey(plan(mode='frame'), tmp_path, adapter=FakeAdapter())
    assert not list(tmp_path.glob('spend*.jsonl'))


def test_the_default_round_issues_no_reads_and_therefore_no_calls(tmp_path):
    adapter = FakeAdapter()
    outcome = r.survey(plan(), tmp_path, adapter=adapter)
    assert outcome['structure'] == [] and outcome['reads'] == []
    assert outcome['collection']['status'] == 'skipped' and outcome['ledger'] == []
    assert adapter.calls == [] and adapter.brand_names == []


def test_a_failed_brand_lookup_costs_only_the_brand_reads(tmp_path):
    adapter = FakeAdapter(brand_failure=r.SourceError('千瓜未找到该品牌；结构层本轮跳过。'))
    outcome = r.survey(plan(mode='frame'), tmp_path, adapter=adapter)
    assert [item['source_grade'] for item in outcome['structure']] == ['trend_series']
    assert outcome['collection']['status'] == 'partial'
    assert any('本轮不含 SOV 与合作结构' in line for line in outcome['collection']['limitations'])
    assert 'brand.get_sov_chart' not in [name for name, _ in adapter.calls]


def test_a_shape_the_reader_does_not_know_is_a_failure_and_not_a_zero(tmp_path):
    adapter = FakeAdapter(bad_shape={'brand.get_sov_chart'})
    outcome = r.survey(plan(mode='frame'), tmp_path, adapter=adapter)
    assert [read_of(item) for item in outcome['structure']] == ['brand_pyramid', 'keyword_trend']
    assert any(error['operation'] == 'brand_sov' for error in outcome['collection']['errors'])
    assert any('SOV 趋势未取到' in line for line in outcome['collection']['limitations'])


def test_an_empty_series_is_reported_as_empty_rather_than_as_a_reading(tmp_path):
    adapter = FakeAdapter(empty={'keyword.note_trends'})
    outcome = r.survey(plan(mode='scan'), tmp_path, adapter=adapter)
    assert outcome['structure'] == [] and outcome['collection']['status'] == 'empty'
    assert any('没有数据点' in line for line in outcome['collection']['limitations'])


def test_a_read_that_never_ran_is_not_reported_as_an_empty_market(tmp_path):
    """The ledger distinguishes "asked and got nothing" from "never asked"."""
    adapter = FakeAdapter(empty={'keyword.note_trends'})
    r.survey(plan(mode='scan'), tmp_path, adapter=adapter)
    assert (tmp_path / 'structure-keyword_trend.json').is_file()
    clean = FakeAdapter()
    r.survey(plan(), tmp_path / 'other', adapter=clean)
    assert not (tmp_path / 'other').exists() or not (tmp_path / 'other' / 'structure-keyword_trend.json').exists()


# --- the editorial side of the same contract -----------------------------------------------


def test_an_aggregate_needs_a_descriptor_where_a_note_needs_a_url():
    aggregate = {'id': 'S1', 'url': '', 'source_grade': 'trend_series',
                 'source': {'vendor': 'qiangua', 'capability': 'keyword.note_trends',
                            'window': {'start_date': '2026-09-01', 'end_date': '2026-09-30'}}}
    assert e._aggregate_sourced(aggregate) is True
    # Half a descriptor fails closed, exactly as a malformed URL would.
    assert e._aggregate_sourced({**aggregate, 'source': {'vendor': 'qiangua'}}) is False
    assert e._aggregate_sourced({**aggregate,
                                 'source': {'vendor': 'qiangua', 'capability': 'x'}}) is False
    assert e._aggregate_sourced({**aggregate, 'source': 'qiangua'}) is False
    assert e._aggregate_sourced({'id': 'E1'}) is False


def test_a_grade_the_vocabulary_does_not_know_is_held_to_the_stricter_rule():
    """Fail-closed: an unknown grade is treated as note text and still needs a URL."""
    assert grades.is_note_text('unverified') is True
    assert grades.is_note_text('typo-grade') is True
    assert grades.is_note_text('brand_structure') is False


def test_a_rendered_source_line_is_a_link_for_a_page_and_a_descriptor_otherwise():
    page = {'id': 'E1', 'title': '笔记标题', 'url': 'https://www.xiaohongshu.com/explore/n1'}
    assert e._source_reference(page, 'E1') == '- [笔记标题](https://www.xiaohongshu.com/explore/n1)'
    aggregate = {'id': 'S1', 'title': 'SOV 趋势', 'url': '',
                 'source': {'vendor': 'qiangua', 'capability': 'brand.get_sov_chart',
                            'window': {'start_date': '2026-09-01', 'end_date': '2026-09-30'}}}
    line = e._source_reference(aggregate, 'S1')
    assert line == '- SOV 趋势（qiangua brand.get_sov_chart 2026-09-01—2026-09-30）'
    # A page-less item never renders as a broken empty link.
    assert ']()' not in line
