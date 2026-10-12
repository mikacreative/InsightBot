"""Modes as an execution decision, not only a price.

METHODOLOGY §4 sizes a round from the strength of the judgement needed, not from how much
material happens to be around. Two things make that true in code rather than in prose: the
mode decides the round's allowances, and the mode's allowances come from the same recipe that
prices it. The rest of these tests cover the ways a mode can still be wrong for a task —
which is reported, in two deliberately different wordings, rather than discovered later.
"""
import pytest

from insightbot.signal_desk import costcontrol as c, research_v2 as r

BRAND = {'id': 'fictional-brand', 'name': '虚构品牌'}
TASK = {'id': 'task1', 'request': '看我们和竞品在同一个窗口里的位置'}


def plan(**inputs):
    return r.create_plan(BRAND, TASK, {'keyword': '测试词', **inputs})


class Adapter:
    """Minimal 千瓜 stand-in: one candidate, no detail, no network."""

    def auth(self):
        return True

    def search(self, query, **kwargs):
        return {'normalized_items': [{'title': '个案', 'url': 'https://www.xiaohongshu.com/explore/n1',
                                      'raw': {'NoteId': 'n1'}}], 'total_count': 1}


def test_every_mode_declares_the_shared_layer_vocabulary():
    for key, mode in r.MODES.items():
        assert set(mode['layers']) <= set(r.LAYERS), key
        assert mode['name'] and mode['cadence'] and mode['output'] and mode['trigger'], key
        assert key in c.RECIPE_CALLS and key in c.RECIPE_ALLOWANCES, key


def test_the_default_round_is_unchanged_by_modes_existing():
    """Naming no mode must not resize a round: probe's allowances are BUDGET_DEFAULTS."""
    assert r.DEFAULT_MODE == 'probe'
    assert r.mode_budget() == r.BUDGET_DEFAULTS
    assert r.mode_budget('probe') == r.BUDGET_DEFAULTS
    assert plan(task_type='content')['mode'] == 'probe'


def test_mode_allowances_come_from_the_recipe_that_prices_the_mode():
    """One number per fact: a mode must not be quoted at one cost and execute at another."""
    for key, recipe in c.RECIPE_CALLS.items():
        assert r.mode_budget(key)['queries'] == recipe[c.SEARCH_V4], key
        assert r.mode_budget(key)['body_reads'] == recipe[c.DETAIL_V1], key
    bodies = [r.mode_budget(key)['body_reads'] for key in ('scan', 'probe', 'frame')]
    assert bodies == [1, 3, 6]


def test_allowances_do_not_follow_a_later_change_to_the_endpoint_constants(monkeypatch):
    """A zero allowance is a policy statement, so it must not be reachable by accident.

    Looking the recipe up by constant at call time does exactly that: point DETAIL_V1 at
    another version the recipe does not mention and body_reads silently becomes 0, which
    looks like a deliberate decision not to buy bodies at all. RECIPE_ALLOWANCES is resolved
    once, at import, for that reason.
    """
    before = r.mode_budget('probe')['body_reads']
    monkeypatch.setattr(c, 'DETAIL_V1', '/api/xiaohongshu/get-note-detail/v6')
    assert r.mode_budget('probe')['body_reads'] == before


def test_a_scan_plan_carries_scan_allowances():
    scan = plan(mode='scan', task_type='content')
    assert scan['mode'] == 'scan' and scan['mode_layers'] == ['L1', 'T']
    assert scan['budget']['body_reads'] == 1 and scan['budget']['queries'] == 2
    assert r.execution_budget(scan)['body_reads'] == 1
    assert plan(mode='frame', task_type='content')['budget']['body_reads'] == 6


def test_the_frozen_plan_decides_the_round_not_its_mode_label():
    """A plan approved as a scan must not grow into a probe because MODES changed."""
    frozen = {**r.mode_budget('scan'), 'enrichment_rounds': 1}
    assert r.execution_budget({'mode': 'probe', 'budget': frozen})['body_reads'] == 1


def test_an_explicit_budget_overrides_the_mode_and_the_caps_still_hold():
    assert plan(mode='frame', task_type='content', budget={'body_reads': 2})['budget']['body_reads'] == 2
    with pytest.raises(ValueError, match='body_reads'):
        plan(mode='frame', task_type='content', budget={'body_reads': 9})


def test_modes_are_resolved_by_alias_and_an_unknown_one_is_refused():
    assert plan(mode='速读', task_type='content')['mode'] == 'scan'
    assert plan(mode='FRAME', task_type='content')['mode'] == 'frame'
    # Not rounded to the nearest mode: the mode decides how much a round may spend.
    with pytest.raises(ValueError, match='研究模式'):
        plan(mode='deep-dive', task_type='content')


def test_a_mode_too_small_for_the_task_is_reported_as_a_mode_shortfall():
    """§3.8 says what the task needs, §4 says what the mode reaches; the difference shows."""
    assert r.mode_shortfall('scan', 'brand_competition') == ['L3']
    assert r.mode_shortfall('frame', 'brand_competition') == []
    assert r.mode_shortfall('probe', 'data_change') == ['T']
    scan = plan(mode='scan', task_type='brand_competition')
    assert any('速读' in line and '未覆盖' in line and 'L3' in line for line in scan['limitations'])


def test_the_pipeline_gap_and_the_mode_gap_are_worded_apart():
    """One is fixed by shipping a reader, the other by choosing a bigger mode."""
    # The mode gap alone, with no pipeline gap to confuse it with: 品牌与竞争 stopped carrying
    # one when L3 landed, and 速读 simply does not gather L3.
    covered = plan(mode='scan', task_type='brand_competition')
    assert any('未覆盖' in line and 'L3' in line for line in covered['limitations'])
    assert not any('未接入' in line for line in covered['limitations'])
    # The pipeline gap alone: no mode reaches L4, so 结构 is as far as this gets.
    product = plan(mode='frame', task_type='product')
    assert any('未接入' in line and 'L4' in line for line in product['limitations'])
    # And both at once — 人群与使用情境 under 速读 lacks L2 twice over, which is the case
    # §9.2 calls 两头都缺: the wording must not let one stand in for the other.
    scan = plan(mode='scan', task_type='audience')
    assert any('未接入' in line and 'L2' in line for line in scan['limitations'])
    assert any('未覆盖' in line and 'L2' in line for line in scan['limitations'])


def test_the_run_repeats_the_mode_it_used_and_what_it_could_not_answer(tmp_path):
    scan = plan(mode='scan', task_type='brand_competition')
    collected = r.collect(scan, tmp_path / 'scan', adapter=Adapter())
    assert collected['collection']['mode'] == 'scan'
    assert any('速读' in line and '未覆盖' in line for line in collected['collection']['limitations'])
    covered = r.collect(plan(mode='probe', task_type='content'), tmp_path / 'probe', adapter=Adapter())
    assert covered['collection']['mode'] == 'probe'
    assert not any('未覆盖' in line for line in covered['collection']['limitations'])
