"""The spend gate in front of the only paid call the pipeline makes.

A token alone must not spend. Money moves only under a declared envelope, every paid body
read reserves *before* it is issued, and it settles afterwards with the code the vendor
returned — so a call that failed gives its budget back instead of holding it forever.

These drive the real gate rather than a stand-in. A spend control proven only through a
fake is not a proven spend control, and the failure it prevents (double-spending one
balance from two channels) stays invisible until the statement arrives.
"""
from authorization_helpers import approved_plan

import copy
import hashlib
from decimal import Decimal

from insightbot.signal_desk import costcontrol as c, editorial_v2 as e, providers, research_v2 as r

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


def plan():
    return r.create_plan(BRAND, TASK, {'keyword': '笔芯兼容'})


def collected():
    return {'evidence': copy.deepcopy(EVIDENCE),
            'collection': {'status': 'complete', 'errors': []},
            'external_context': [], 'ledger': []}


def draft():
    return e.parse_protocol(GAP_TEXT)


def envelope(limit='5'):
    return c.Envelope(BRAND['id'], c.period_of(), Decimal(limit))


def spend(tmp_path, limit='5'):
    return {'envelope': envelope(limit), 'spend_ledger': tmp_path / 'spend.jsonl'}


def ledger_rows(tmp_path):
    return [row for row in c.load_ledger(tmp_path / 'spend.jsonl') if row.get('kind') in ('reserve', 'settle')]


class PaidReader:
    """Stands in for JustOneAPI: configured, and able to return note text."""

    configured = True

    def __init__(self, failure=None):
        self.failure = failure
        self.urls = []

    def detail(self, url):
        self.urls.append(url)
        if self.failure is not None:
            raise self.failure
        return {'code': 0, 'data': [{'model_type': 'note', 'note_list': [
            {'id': 'n1', 'title': '替换笔芯的兼容问题',
             'desc': '笔杆型号刻在笔夹内侧，我按型号对照表确认兼容。', 'time': 1791540718}]}]}


class FreeReader:
    """Stands in for 千瓜's fragment read: no content field, and no charge."""

    configured = True

    def __init__(self):
        self.urls = []

    def detail(self, url):
        self.urls.append(url)
        return {'normalized_note': {'url': url, 'raw': {'NoteId': 'n1', 'Content': '只有片段'}}}


# --- reserving and settling ---------------------------------------------------------------

def test_a_paid_read_reserves_before_the_call_and_settles_with_the_vendor_code(tmp_path):
    reader = PaidReader()
    result = r.enrich(approved_plan(plan(), tmp_path, limit='5'), collected(), draft(), tmp_path, adapter=FreeReader(),
                      body_adapter=reader, **spend(tmp_path))
    assert reader.urls == [NOTE_URL]
    assert result['evidence'][0]['source_grade'] == 'note_body'

    reserve, settle = ledger_rows(tmp_path)
    assert reserve['kind'] == 'reserve' and reserve['channel'] == 'rest'
    assert reserve['scope'] == BRAND['id'] and reserve['period'] == c.period_of()
    assert reserve['lines'][0]['endpoint'] == c.DETAIL_V1 and reserve['lines'][0]['calls'] == 1
    assert Decimal(reserve['lines'][0]['unit_price']) == Decimal('0.15')
    # Settled by code, not by estimate. Here the table and the vendor agree, which is
    # exactly the case where a settle that guessed would be hardest to notice.
    assert settle['kind'] == 'settle' and settle['code'] == 0
    assert Decimal(settle['actual_cny']) == Decimal('0.15') and settle['variance_cny'] == '0.0000'
    assert c.remaining(ledger_rows(tmp_path), envelope()) == Decimal('4.85')


def test_a_failed_body_read_settles_at_zero_and_gives_the_budget_back(tmp_path):
    """The vendor bills code=0 only, so a hold that was never billed must be released."""
    reader = PaidReader(failure=providers.ProviderError('采集失败', code=301))
    result = r.enrich(approved_plan(plan(), tmp_path, limit='5'), collected(), draft(), tmp_path, adapter=FreeReader(),
                      body_adapter=reader, **spend(tmp_path))
    assert reader.urls == [NOTE_URL]
    assert result['evidence'][0]['source_grade'] == 'note_meta'
    assert result['enrichment']['outcomes'][0]['status'] == 'failed'

    settle = ledger_rows(tmp_path)[1]
    assert settle['code'] == 301 and settle['billed'] is False
    assert settle['actual_cny'] == '0' and settle['variance_cny'] == '-0.1500'
    assert c.remaining(ledger_rows(tmp_path), envelope()) == Decimal('5')


def test_a_cached_body_neither_reserves_nor_bills(tmp_path):
    """A cache hit is not a call. Reserving for it would charge for nothing."""
    directory = tmp_path / 'run'
    directory.mkdir()
    key = hashlib.sha256(NOTE_URL.encode()).hexdigest()[:24]
    (directory / f'enrich-detail-justoneapi-{key}.json').write_text(
        '{"code": 0, "data": [{"note_list": [{"id": "n1", "desc": "缓存中的正文，虚构文本。"}]}]}',
        encoding='utf-8')
    paid, free = PaidReader(), FreeReader()
    result = r.enrich(approved_plan(plan(), tmp_path, limit='5'), collected(), draft(), directory, adapter=free,
                      body_adapter=paid, **spend(tmp_path))
    assert paid.urls == [] and result['evidence'][0]['excerpt'] == '缓存中的正文，虚构文本。'
    assert ledger_rows(tmp_path) == []


def test_an_exhausted_envelope_stops_before_calling_the_source(tmp_path):
    reader = PaidReader()
    result = r.enrich(approved_plan(plan(), tmp_path, limit='0.10'), collected(), draft(), tmp_path, adapter=FreeReader(),
                      body_adapter=reader, **spend(tmp_path, limit='0.10'))
    assert reader.urls == [] and ledger_rows(tmp_path) == []
    assert result['enrichment']['attempted'] == 0
    assert result['enrichment']['reason'] == 'budget_denied'
    assert result['enrichment']['outcomes'][0]['status'] == 'skipped'
    assert result['enrichment']['outcomes'][0]['reason'] == 'budget_denied'
    assert result['collection']['errors'][0]['source'] == 'costcontrol'


def test_an_unpriced_endpoint_is_refused_rather_than_read_for_free(tmp_path, monkeypatch):
    """The gate fails closed: if it cannot price the call, it does not make it."""
    approved = approved_plan(plan(), tmp_path)
    monkeypatch.setattr(r.costcontrol, 'DETAIL_V1', '/api/xiaohongshu/not-a-real-endpoint/v9')
    reader = PaidReader()
    result = r.enrich(approved, collected(), draft(), tmp_path, adapter=FreeReader(),
                      body_adapter=reader, **spend(tmp_path))
    assert reader.urls == [] and ledger_rows(tmp_path) == []
    assert result['enrichment']['reason'] == 'budget_denied'


# --- the gate is a deployment decision, not a default -------------------------------------

def test_a_token_without_a_declared_envelope_does_not_spend(tmp_path, monkeypatch):
    """Enough to buy bodies is not permission to buy them."""
    monkeypatch.setenv(providers.JustOneApiAdapter.TOKEN_ENV, 'fictional-token')
    monkeypatch.delenv(c.SPEND_LIMIT_ENV, raising=False)
    free = FreeReader()
    result = r.enrich(plan(), collected(), draft(), tmp_path, adapter=free,
                      spend_ledger=tmp_path / 'spend.jsonl')
    assert providers.JustOneApiAdapter().configured is True
    assert free.urls == [NOTE_URL] and ledger_rows(tmp_path) == []
    assert result['evidence'][0]['source_grade'] == 'note_segment'
    # Reported, not silent: whoever set a token and no ceiling should learn it here.
    assert [line for line in result['collection']['limitations'] if '花费额度' in line]


def test_the_default_body_reader_is_the_real_adapter(tmp_path, monkeypatch):
    """Nothing in production injects it, so the default has to be the one that spends."""
    reader = PaidReader()
    monkeypatch.setattr(providers, 'JustOneApiAdapter', lambda *args, **kwargs: reader)
    result = r.enrich(approved_plan(plan(), tmp_path, limit='5'), collected(), draft(), tmp_path, adapter=FreeReader(), **spend(tmp_path))
    assert reader.urls == [NOTE_URL]
    assert result['evidence'][0]['source_grade'] == 'note_body'


def test_environment_alone_cannot_authorize_an_unapproved_plan(tmp_path, monkeypatch):
    reader = PaidReader()
    monkeypatch.setattr(providers, 'JustOneApiAdapter', lambda *args, **kwargs: reader)
    monkeypatch.setenv(c.SPEND_LIMIT_ENV, '1.00')
    monkeypatch.setenv(c.SPEND_LEDGER_ENV, str(tmp_path / 'spend.jsonl'))
    result = r.enrich(plan(), collected(), draft(), tmp_path, adapter=FreeReader())
    assert reader.urls == []
    assert result['evidence'][0]['source_grade'] == 'note_segment'
    assert ledger_rows(tmp_path) == []


def test_the_envelope_belongs_to_the_brand_not_the_run(tmp_path):
    """Two runs for one brand draw on one ceiling; a per-run ceiling means nothing."""
    shared = spend(tmp_path, limit='0.20')
    first = r.enrich(approved_plan(plan(), tmp_path, limit='0.20'), collected(), draft(), tmp_path / 'first', adapter=FreeReader(),
                     body_adapter=PaidReader(), **shared)
    second = r.enrich(approved_plan(plan(), tmp_path, limit='0.20'), collected(), draft(), tmp_path / 'second', adapter=FreeReader(),
                      body_adapter=PaidReader(), **shared)
    assert first['evidence'][0]['source_grade'] == 'note_body'
    assert second['enrichment']['reason'] == 'budget_denied'
    settled = [row['actual_cny'] for row in ledger_rows(tmp_path) if row['kind'] == 'settle']
    assert settled == ['0.1500']
    assert c.remaining(ledger_rows(tmp_path), envelope('0.20')) == Decimal('0.05')


def test_a_paid_read_records_the_mode_that_authorised_it(tmp_path):
    """One envelope carries every mode in the period, so spend must be separable by mode.

    Without the stamp, a Frame's real cost cannot be compared with the recipe quoted for it,
    and the breakdown that would show a mode's estimate drifting from reality is unavailable
    exactly where it matters.
    """
    framed = r.create_plan(BRAND, TASK, {'keyword': '笔芯兼容', 'mode': 'frame'})
    r.enrich(approved_plan(framed, tmp_path, limit='5'), collected(), draft(), tmp_path, adapter=FreeReader(),
             body_adapter=PaidReader(), **spend(tmp_path))
    assert ledger_rows(tmp_path)[0]['mode'] == 'frame'
    assert ledger_rows(tmp_path)[1]['mode'] == 'frame'
    state = c.report(BRAND['id'], c.period_of(), '5', ledger=tmp_path / 'spend.jsonl')
    assert state['by_mode'] == {'frame': 1} and state['spent_by_mode'] == {'frame': '0.1500'}
    assert c.report(BRAND['id'], c.period_of(), '5', mode='scan',
                    ledger=tmp_path / 'spend.jsonl')['consumed_cny'] == '0'
