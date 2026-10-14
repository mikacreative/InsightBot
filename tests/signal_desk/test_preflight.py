"""执行前契约体检：冻结接口、零稿风险的二元判断、以及批准与执行读同一个信封。

设计稿 `docs/signal-desk/PREFLIGHT-DESIGN-v0.1.md` §7.3 把这些键名与取值域定死，所以这里
**驱动真函数**：preflight 是纯函数、enrich 走真的花费关口，都不造替身。一个只在假体上
成立的风险判断，等于没有判断。

本文件覆盖的边界（都是设计稿里敢断言的那些，不敢断言的一律留白）：
* `H == 0` 的三条独立成因（未声明信封／余量用尽／配额为 0）都得出 `zero_risk='high'`；
* 免费的**结构层**读取能把 H 抬起来，所以"某模式不采某层"**单独**不构成断言（§6①-5）；
* `H > 0` 只有"未知"：不给零稿概率、不断言零稿（上界条数本身照常出现在 notes 里）；
* `contract.envelope` 是批准那一刻的快照，`enrich` 读快照而非现读 env（裁定 3）；
* `plan_hash` 对两个派生键不敏感、对其余键敏感（§7.3-③）。
"""
from authorization_helpers import approved_plan

import copy
from decimal import Decimal

from insightbot.signal_desk import costcontrol as c, editorial_v2 as e, research_v2 as r

BRAND = {'id': 'fictional-brand', 'name': '虚构品牌'}
TASK = {'id': 'task1', 'request': '理解替换笔芯的兼容说明为何让用户困惑'}
NOTE_URL = 'https://www.xiaohongshu.com/explore/n1'
EVIDENCE = [{'id': 'E1', 'title': '替换笔芯的兼容问题', 'excerpt': '替换笔芯的兼容问题',
             'url': NOTE_URL, 'source_id': 'n1', 'providers': ['qiangua'],
             'source_grade': 'note_meta', 'query': '笔芯兼容',
             'snapshots': [{'provider': 'qiangua', 'excerpt': '替换笔芯的兼容问题'}]}]
GAP_TEXT = '\n'.join([
    'CANDIDATE|C01|research|兼容表达可能让选购产生困惑|E1|-|标题不足以判断具体原因',
    'GAP|C01|E1|未读正文，无法区分型号与规格表达|具体经历可改变个案是否入选',
    'SCOPE|本轮限定笔芯相关查询；仅有标题，尚不能形成精选判断。'])


class PaidReader:
    """Stand-in for JustOneAPI: configured, and able to return note text."""

    configured = True

    def __init__(self):
        self.urls = []

    def detail(self, url):
        self.urls.append(url)
        return {'code': 0, 'data': [{'model_type': 'note', 'note_list': [
            {'id': 'n1', 'title': '替换笔芯的兼容问题',
             'desc': '笔杆型号刻在笔夹内侧，我按型号对照表确认兼容。', 'time': 1791540718}]}]}


class FreeReader:
    """Stand-in for 千瓜's fragment read: no content field, and no charge."""

    configured = True

    def __init__(self):
        self.urls = []

    def detail(self, url):
        self.urls.append(url)
        return {'normalized_note': {'url': url, 'raw': {'NoteId': 'n1', 'Content': '只有片段'}}}


def collected():
    return {'evidence': copy.deepcopy(EVIDENCE),
            'collection': {'status': 'complete', 'errors': []},
            'external_context': [], 'ledger': []}


def draft():
    return e.parse_protocol(GAP_TEXT)


def plan(**inputs):
    return r.create_plan(BRAND, TASK, {'keyword': '笔芯兼容', **inputs})


def isolated_ledger(tmp_path, monkeypatch, limit=None):
    """Point both environment read-points at scratch state, so no test reads real spend.

    The ledger must be isolated even when no envelope is declared: `report` is only called
    under an envelope, but the default ledger path is a file in the repository.
    """
    monkeypatch.setenv(c.SPEND_LEDGER_ENV, str(tmp_path / 'spend.jsonl'))
    if limit is None:
        monkeypatch.delenv(c.SPEND_LIMIT_ENV, raising=False)
    else:
        monkeypatch.setenv(c.SPEND_LIMIT_ENV, limit)


def lines_with(block, key, fragment):
    return [line for line in block[key] if fragment in line]


def note_with(preflight, fragment):
    return lines_with(preflight, 'notes', fragment)


# --- H == 0 的三条独立成因，每条都只能得出 'high'，且不阻断 -------------------------------

def test_no_declared_envelope_leaves_no_paid_path_and_asserts_zero_output(tmp_path, monkeypatch):
    isolated_ledger(tmp_path, monkeypatch)
    p = plan()
    assert p['preflight']['envelope_present'] is False
    assert p['preflight']['envelope_remaining_cny'] is None
    assert p['preflight']['spend_overrun_cny'] is None
    assert p['preflight']['structure_reads'] == []
    assert p['preflight']['non_summary_capacity'] == 0
    assert p['preflight']['zero_risk'] == 'high'
    # 措辞必须是"确定"级：这是全仓唯一敢断言零稿的分支。
    assert note_with(p['preflight'], '确定本轮不会产出卡片')
    assert note_with(p['preflight'], c.SPEND_LIMIT_ENV)


def test_an_exhausted_envelope_removes_the_paid_path_even_though_one_is_declared(
        tmp_path, monkeypatch):
    """信封存在但余量为 0：通路不可用，与"没有信封"殊途同归，但措辞必须不同。"""
    isolated_ledger(tmp_path, monkeypatch, limit='0')
    p = plan()
    assert p['preflight']['envelope_present'] is True
    assert p['preflight']['envelope_remaining_cny'] == '0'
    assert p['preflight']['non_summary_capacity'] == 0
    assert p['preflight']['zero_risk'] == 'high'
    assert note_with(p['preflight'], '已用尽')
    assert not note_with(p['preflight'], c.SPEND_LIMIT_ENV)


def test_zero_paid_quota_with_a_funded_envelope_still_yields_high(tmp_path, monkeypatch):
    """配额为 0：钱在那儿，但这轮没被批准买正文或评论。"""
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    p = plan(budget={'body_reads': 0, 'comment_reads': 0})
    assert p['preflight']['envelope_present'] is True
    assert p['preflight']['envelope_remaining_cny'] == '5'
    assert p['preflight']['non_summary_capacity'] == 0
    assert p['preflight']['zero_risk'] == 'high'


def test_a_mode_that_gathers_no_structure_layer_is_not_by_itself_an_assertion(
        tmp_path, monkeypatch):
    """模式缺口（§4.3 成因③）单独出现时**不得**断言零稿：付费通路还活着，H > 0。"""
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    p = plan(task_type='brand_competition', mode='probe')
    assert p['preflight']['mode_shortfall'] == ['L3']
    assert p['preflight']['structure_reads'] == []
    assert p['preflight']['non_summary_capacity'] == p['budget']['body_reads'] > 0
    assert p['preflight']['zero_risk'] == 'unknown'


def test_a_free_structure_layer_lifts_capacity_with_no_envelope_at_all(tmp_path, monkeypatch):
    """品牌与竞争 × 结构：三层结构读取都不花钱，所以没有信封也**不能**断言零稿。"""
    isolated_ledger(tmp_path, monkeypatch)
    p = plan(task_type='brand_competition', mode='frame')
    assert p['preflight']['unreadable_primary_layers'] == []
    assert p['preflight']['structure_reads'] == ['brand_sov', 'brand_pyramid', 'keyword_trend']
    assert p['preflight']['non_summary_capacity'] == 3
    assert p['preflight']['zero_risk'] == 'unknown'


def test_h_above_zero_is_reported_as_unknown_without_a_probability(tmp_path, monkeypatch):
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    p = plan()
    pf = p['preflight']
    assert pf['non_summary_capacity'] > 0 and pf['zero_risk'] == 'unknown'
    assert pf['zero_risk'] in ('high', 'unknown')      # 只有两值，不给概率
    assert not note_with(pf, '确定本轮不会产出卡片')     # 不承诺零稿，也不承诺产出
    assert all('%' not in line for line in pf['notes'])


def test_a_thin_envelope_reports_the_predicted_overrun_and_keeps_the_paid_path(
        tmp_path, monkeypatch):
    """余量小于配方上界：预警超支额，但通路还没断（§5.1 批准时口径）。"""
    isolated_ledger(tmp_path, monkeypatch, limit='0.10')
    p = plan()
    pf = p['preflight']
    ceiling = c.quote_recipe(p['mode'])
    assert pf['spend_ceiling_cny'] == str(ceiling)
    assert pf['envelope_remaining_cny'] == '0.10'
    assert pf['spend_overrun_cny'] == str(ceiling - Decimal('0.10'))
    assert pf['non_summary_capacity'] > 0 and pf['zero_risk'] == 'unknown'
    assert note_with(pf, '超出信封余量')


def test_preflight_never_touches_ready_or_planning_errors(tmp_path, monkeypatch):
    """体检是警告，不是准入：H == 0 也要能批准（硬拒只发生在定时配置关口）。"""
    isolated_ledger(tmp_path, monkeypatch)
    p = plan()
    assert p['preflight']['zero_risk'] == 'high'
    assert p['planning_errors'] == [] and p['ready'] is True


def test_the_two_shortfalls_are_worded_apart(tmp_path, monkeypatch):
    """管线缺读取器（未接入）与模式不采该层（未覆盖）是两种失败，不能混成一句。"""
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    p = plan(task_type='audience', mode='scan')
    assert p['preflight']['unreadable_primary_layers'] == ['L2']
    assert p['preflight']['mode_shortfall'] == ['L2']
    assert note_with(p['preflight'], '未接入')
    assert note_with(p['preflight'], '模式未覆盖')
    assert not any('未接入' in line and '未覆盖' in line for line in p['preflight']['notes'])


# --- 契约快照：批准即承诺（裁定 3） ------------------------------------------------------

def test_the_contract_snapshots_the_envelope_read_at_approval(tmp_path, monkeypatch):
    isolated_ledger(tmp_path, monkeypatch, limit='2.50')
    p = plan()
    assert p['contract']['envelope'] == {'scope': BRAND['id'], 'period': c.period_of(),
                                         'limit_cny': '2.50', 'source': 'env'}
    # 其余字段是引用，不是第二份真值。
    assert p['contract']['mode'] == p['mode']
    assert p['contract']['mode_layers'] is p['mode_layers']
    assert p['contract']['structure_intent'] is p['structure']
    assert p['contract']['allowances'] is p['budget']
    assert p['contract']['delivery_profile'] is p['delivery_profile']
    assert p['contract']['source_guards'] == {'qiangua_mandatory': True,
                                              'evidence_floor': '非摘要证据 ≥ 1 条 / 卡片'}


def test_the_contract_envelope_is_absent_when_none_was_declared(tmp_path, monkeypatch):
    isolated_ledger(tmp_path, monkeypatch)
    p = plan()
    assert p['contract']['envelope'] is None
    # 批准时没有信封，不该因为之后有人设了环境变量就变成有。
    monkeypatch.setenv(c.SPEND_LIMIT_ENV, '9')
    assert p['contract']['envelope'] is None


# --- plan_hash 只认"要做什么"，不认派生量（§7.3-③） --------------------------------------

def test_plan_hash_ignores_the_derived_keys_and_follows_the_rest(tmp_path, monkeypatch):
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    p = plan()
    derived_only = {**p, 'contract': {'version': 'other'}, 'preflight': {'zero_risk': 'high'}}
    assert r._plan_hash(p) == r._plan_hash(derived_only)
    for key, value in (('keyword', '别的词'), ('mode', 'frame'), ('budget', {'samples': 19})):
        changed = {**p, key: value}
        assert r._plan_hash(p) != r._plan_hash(changed), key


def test_an_existing_collection_cache_survives_a_recomputed_preflight(tmp_path, monkeypatch):
    """派生量变化不该让缓存失效：否则别人花掉一笔钱就会让本轮的采集记录作废。"""
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    p = plan()
    cached = {'plan_hash': r._plan_hash(p), 'evidence': [], 'external_context': [],
              'collection': {'status': 'empty', 'errors': []}, 'ledger': []}
    r.private_json(tmp_path / 'collection-v2.json', cached)
    assert r.collect({**p, 'preflight': {'zero_risk': 'high'}}, tmp_path, adapter=object()) == cached


# --- enrich 读快照，不读现读的 env（裁定 3 的行为变更） ------------------------------------

def test_enrich_spends_against_the_approved_snapshot_not_the_current_environment(
        tmp_path, monkeypatch):
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    approved = approved_plan(plan(), tmp_path)
    monkeypatch.delenv(c.SPEND_LIMIT_ENV, raising=False)     # 批准后额度被撤掉
    paid = PaidReader()
    result = r.enrich(approved, collected(), draft(), tmp_path / 'run', adapter=FreeReader(),
                      body_adapter=paid, spend_ledger=tmp_path / 'spend.jsonl')
    assert paid.urls == [NOTE_URL]
    assert result['evidence'][0]['source_grade'] == 'note_body'
    rows = [row for row in c.load_ledger(tmp_path / 'spend.jsonl') if row.get('kind') in ('reserve', 'settle')]
    assert [row['kind'] for row in rows] == ['reserve', 'settle']


def test_enrich_does_not_start_spending_when_the_snapshot_recorded_no_envelope(
        tmp_path, monkeypatch):
    """反向同样成立：批准时没有信封，执行时环境里出现了也不花一分钱，且不报错。"""
    isolated_ledger(tmp_path, monkeypatch)
    approved = plan()
    monkeypatch.setenv(c.SPEND_LIMIT_ENV, '5')               # 批准后额度被加上
    paid, free = PaidReader(), FreeReader()
    result = r.enrich(approved, collected(), draft(), tmp_path / 'run', adapter=free,
                      body_adapter=paid, spend_ledger=tmp_path / 'spend.jsonl')
    assert paid.urls == [] and free.urls == [NOTE_URL]
    assert result['evidence'][0]['source_grade'] == 'note_segment'
    assert lines_with(result['collection'], 'limitations', '花费额度授权')
    assert c.load_ledger(tmp_path / 'spend.jsonl') == []


def test_an_older_plan_without_a_grant_never_gains_paid_rights_from_environment(tmp_path, monkeypatch):
    """快照功能上线前批准的计划没有 contract 键：回退现读 env，不能崩。"""
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    older = plan()
    older.pop('contract')
    paid = PaidReader()
    result = r.enrich(older, collected(), draft(), tmp_path / 'run', adapter=FreeReader(),
                      body_adapter=paid, spend_ledger=tmp_path / 'spend.jsonl')
    assert paid.urls == []
    assert result['evidence'][0]['source_grade'] == 'note_segment'


def test_a_plan_with_no_brand_id_cannot_hold_an_envelope(tmp_path, monkeypatch):
    """没有品牌归属就没有信封：一个不绑定 scope 的上限会在两个品牌间被重复用掉。"""
    isolated_ledger(tmp_path, monkeypatch, limit='5')
    p = r.create_plan({'name': '无编号品牌'}, TASK, {'keyword': '笔芯兼容'})
    assert p['brand_id'] is None
    assert p['preflight']['envelope_present'] is False
    assert p['contract']['envelope'] is None
