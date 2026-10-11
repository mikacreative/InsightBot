"""Task-to-layer declarations, and the gap they make visible.

METHODOLOGY §2 defines five evidence layers; §3.8 records which decision tasks lean on
which. Writing that down in code is only worth something if a declared layer the pipeline
cannot reach gets reported, instead of being discovered by hand months later. That check
is what these tests pin.
"""
from insightbot.signal_desk import research_v2 as r

BRAND = {'id': 'fictional-brand', 'name': '虚构品牌'}
TASK = {'id': 'task1', 'request': '看我们和竞品在同一个窗口里的位置'}


def test_every_task_speaks_the_shared_layer_vocabulary():
    for key, method in r.METHODS.items():
        assert set(method['layers']) <= set(r.LAYERS), key
        assert set(method['layers'].values()) <= {r.LAYER_PRIMARY, r.LAYER_AUX}, key
        assert r.LAYER_PRIMARY in method['layers'].values(), f'{key} declares nothing it needs'


def test_tasks_needing_an_unreachable_layer_are_reported():
    """The check that would have caught 品牌与竞争 running on L1 retrieval alone."""
    gaps = {gap['task_type']: gap['missing_primary'] for gap in r.layer_gaps()}
    assert gaps['brand_competition'] == ['L3']
    assert gaps['audience'] == ['L2']
    assert gaps['data_change'] == ['T']
    assert set(gaps) == {'brand_competition', 'product', 'audience', 'data_change'}


def test_a_pipeline_that_covers_every_layer_reports_no_gaps():
    assert r.layer_gaps(dict.fromkeys(r.LAYERS, 'reader')) == []


def test_a_missing_auxiliary_layer_is_a_weakening_not_a_gap():
    """平台与渠道 needs L1 only; an absent L2 or T must not be filed as a gap."""
    assert r.METHODS['platform']['layers'] == {'L1': r.LAYER_PRIMARY, 'L2': r.LAYER_AUX, 'T': r.LAYER_AUX}
    assert r.missing_primary_layers('platform') == []
    assert r.missing_primary_layers('platform', {'L1': 'reader'}) == []


def test_the_plan_states_its_layers_and_names_the_missing_one():
    plan = r.create_plan(BRAND, TASK, {'keyword': '测试词', 'task_type': 'brand_competition'})
    assert plan['layers']['L3'] == r.LAYER_PRIMARY and plan['task_type'] == 'brand_competition'
    assert any('未接入' in line and 'L3' in line for line in plan['limitations'])


def test_a_task_with_no_missing_primary_layer_carries_no_gap_line():
    plan = r.create_plan(BRAND, TASK, {'keyword': '测试词', 'task_type': 'content'})
    assert not any('未接入' in line for line in plan['limitations'])


class Adapter:
    """Minimal 千瓜 stand-in: one candidate, no detail, no network."""

    def auth(self):
        return True

    def search(self, query, **kwargs):
        return {'normalized_items': [{'title': '个案', 'url': 'https://www.xiaohongshu.com/explore/n1',
                                      'raw': {'NoteId': 'n1'}}], 'total_count': 1}


def test_the_run_itself_states_the_layer_it_could_not_reach(tmp_path):
    """A gap in the plan is easy to miss; it has to reach the run's own output too."""
    plan = r.create_plan(BRAND, TASK, {'keyword': '测试词', 'task_type': 'brand_competition'})
    collected = r.collect(plan, tmp_path / 'gap', adapter=Adapter())
    assert any('未接入' in line and 'L3' in line for line in collected['collection']['limitations'])


def test_a_covered_run_carries_no_gap_line(tmp_path):
    plan = r.create_plan(BRAND, TASK, {'keyword': '测试词', 'task_type': 'content'})
    collected = r.collect(plan, tmp_path / 'covered', adapter=Adapter())
    assert not any('未接入' in line for line in collected['collection']['limitations'])

