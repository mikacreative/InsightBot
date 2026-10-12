"""The L1 comment layer: reader, parser, and the gate it spends through.

Shape verified against a real 2026-10-12 response (note 6ac8bdee00000000140016dc,
one latest page): data is a dict with comments[] — a third shape, different from
detail and search. The parser fails loudly on anything else, because a guessed
shape would misfile comment text as note text or the reverse.

Spending rules are inherited, not new: reserve before the call, settle by code
afterwards, a cache hit neither reserves nor bills, and a comment failure never
fails the body read it rides on.
"""
from decimal import Decimal

import pytest

from insightbot.signal_desk import costcontrol as c, editorial_v2 as e, providers, research_v2 as r

BRAND = {'id': 'fictional-brand', 'name': '虚构品牌'}
TASK = {'id': 'task1', 'request': '理解替换笔芯的兼容说明为何让用户困惑'}
NOTE_URL = 'https://www.xiaohongshu.com/explore/n1'
NOTE_ID = 'n1'
EVIDENCE = [{'id': 'E1', 'title': '替换笔芯的兼容问题', 'excerpt': '替换笔芯的兼容问题',
             'url': NOTE_URL, 'source_id': NOTE_ID, 'providers': ['qiangua'],
             'source_grade': 'note_meta', 'query': '笔芯兼容',
             'snapshots': [{'provider': 'qiangua', 'excerpt': '替换笔芯的兼容问题'}]}]
GAP_TEXT = '\n'.join([
    'CANDIDATE|C01|research|兼容表达可能让选购产生困惑|E1|-|标题不足以判断具体原因',
    'GAP|C01|E1|未读正文，无法区分型号与规格表达|具体经历可改变个案是否入选',
    'SCOPE|本轮限定笔芯相关查询；仅有标题，尚不能形成精选判断。'])


def comment_page(note_id=NOTE_ID, **over):
    """A stub shaped exactly like the verified 2026-10-12 response."""
    page = {'code': 0, 'data': {'comment_count': 473, 'comment_count_l1': 206,
                                'current_sort_strategy': 'latest_v2', 'has_more': True,
                                'cursor': '{"cursor":"c1","index":2}',
                                'comments': [
                                    {'id': 'cm1', 'note_id': note_id, 'content': '蹲一个碱水结',
                                     'ip_location': '浙江', 'like_count': 3, 'time': 1791692112,
                                     'user': {'nickname': '评论者甲'}, 'sub_comment_count': 0,
                                     'sub_comments': []},
                                    {'id': 'cm2', 'note_id': note_id, 'content': ' compatible 吗',
                                     'ip_location': '北京', 'like_count': 0, 'time': 1791625888,
                                     'user': {'nickname': '评论者乙'}, 'sub_comment_count': 1,
                                     'sub_comments': [
                                         {'id': 'cm3', 'note_id': note_id,
                                          'content': '我也想问', 'ip_location': '浙江',
                                          'like_count': 1, 'time': 1791635893,
                                          'user': {'nickname': '评论者丙'},
                                          'sub_comments': []}]}]}}
    page['data'].update(over)
    return page


def plan(**inputs):
    return r.create_plan(BRAND, TASK, {'keyword': '笔芯兼容', **inputs})


def collected():
    return {'evidence': [dict(EVIDENCE[0])],
            'collection': {'status': 'complete', 'errors': []},
            'external_context': [], 'ledger': []}


def draft():
    return e.parse_protocol(GAP_TEXT)


def envelope(limit='5'):
    return c.Envelope(BRAND['id'], c.period_of(), Decimal(limit))


def spend(tmp_path, limit='5'):
    return {'envelope': envelope(limit), 'spend_ledger': tmp_path / 'spend.jsonl'}


def ledger_rows(tmp_path):
    return c.load_ledger(tmp_path / 'spend.jsonl')


class PaidReader:
    """Stands in for JustOneAPI: bodies and comments, both configured."""

    configured = True

    def __init__(self, comment_failure=None):
        self.detail_urls, self.comment_ids = [], []
        self.comment_failure = comment_failure

    def detail(self, url):
        self.detail_urls.append(url)
        return {'code': 0, 'data': [{'note_list': [
            {'id': NOTE_ID, 'title': '替换笔芯的兼容问题',
             'desc': '笔杆型号刻在笔夹内侧，我按型号对照表确认兼容。', 'time': 1791540718}]}]}

    def comments(self, note_id, *, sort='latest', cursor=None):
        self.comment_ids.append(note_id)
        if self.comment_failure is not None:
            raise self.comment_failure
        return comment_page(note_id=note_id)


# --- the parser: one page becomes one thread, and lies are refused ------------------------

def test_one_page_becomes_one_note_comment_thread():
    item = providers.comments_to_evidence(comment_page(), url=NOTE_URL, note_title='替换笔芯')
    assert item['source_grade'] == 'note_comment' and item['source_id'] == NOTE_ID
    assert '评论者甲（浙江）：蹲一个碱水结［赞3］' in item['excerpt']
    # A reply stays in its parent's thread, one indent level deep.
    assert '　评论者丙（浙江）：我也想问' in item['excerpt']
    assert item['comment_total'] == 473 and item['comments_returned'] == 2
    assert item['has_more'] is True and item['latest_comment_at'].startswith('2026-')


def test_a_page_without_comments_is_not_a_comment_thread():
    assert providers.comments_to_evidence(comment_page(comments=[]), url=NOTE_URL) is None


def test_a_broken_shape_is_refused_not_guessed():
    with pytest.raises(RuntimeError, match='comment schema'):
        providers.comments_to_evidence({'code': 0, 'data': []})
    with pytest.raises(RuntimeError, match='comment schema'):
        providers.comments_to_evidence(comment_page(comments=[{'content': '没有note_id'}]))


def test_comments_for_another_note_are_refused():
    with pytest.raises(RuntimeError, match='different note'):
        providers.comments_to_evidence(comment_page(note_id='other-note'), url=NOTE_URL)


def test_reader_builds_the_documented_request(monkeypatch):
    seen = {}

    class Response:
        status_code = 200

        def json(self):
            return comment_page()

    def fake_get(url, params=None, timeout=None, **kwargs):
        seen.update(url=url, params=params)
        return Response()

    monkeypatch.setattr(providers.httpx, 'get', fake_get)
    providers.justone_note_comment('6ac8bdee00000000140016dc', 'tok', cursor='c9')
    assert seen['url'].endswith('/api/xiaohongshu/get-note-comment/v2')
    assert seen['params']['noteId'] == '6ac8bdee00000000140016dc'
    assert seen['params']['sort'] == 'latest' and seen['params']['lastCursor'] == 'c9'
    with pytest.raises(ValueError, match='sort'):
        providers.justone_note_comment('n1', 'tok', sort='hot')


def test_reader_propagates_the_vendor_code(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {'code': 303, 'message': '超出每日配额'}

    monkeypatch.setattr(providers.httpx, 'get', lambda *a, **k: Response())
    with pytest.raises(providers.ProviderError) as caught:
        providers.justone_note_comment('n1', 'tok')
    assert caught.value.code == 303


# --- the enrich pass: gated per page, riding on body targets ------------------------------

def test_comments_are_off_by_default_and_cost_nothing(tmp_path):
    reader = PaidReader()
    result = r.enrich(plan(), collected(), draft(), tmp_path, adapter=_free(),
                      body_adapter=reader, **spend(tmp_path))
    assert reader.comment_ids == [] and result['enrichment'].get('comment_attempted') is None
    assert result['collection']['comments'] == 0


def test_a_budgeted_comment_page_is_gated_settled_and_attached(tmp_path):
    reader = PaidReader()
    result = r.enrich(plan(budget={'comment_reads': 1}), collected(), draft(), tmp_path,
                      adapter=_free(), body_adapter=reader, **spend(tmp_path))
    assert reader.comment_ids == [NOTE_ID]
    threads = [item for item in result['evidence'] if item['source_grade'] == 'note_comment']
    assert len(threads) == 1 and threads[0]['id'] == 'E1-comments'
    assert threads[0]['snapshots'][0]['candidate_ids'] == ['C01']
    assert result['collection']['comments'] == 1 and result['enrichment']['comments_added'] == 1

    comment_reserves = [row for row in ledger_rows(tmp_path) if row['kind'] == 'reserve'
                        and c.COMMENT_V2 in [line['endpoint'] for line in row['lines']]]
    assert len(comment_reserves) == 1
    assert comment_reserves[0]['mode'] == 'probe'
    settles = [row for row in ledger_rows(tmp_path) if row['kind'] == 'settle']
    assert Decimal(settles[-1]['actual_cny']) == Decimal('0.15')
    assert settles[-1]['note'] == r.COMMENT_OPERATION


def test_a_failed_comment_page_settles_at_zero_and_keeps_the_body(tmp_path):
    failure = providers.ProviderError('采集失败', code=301)
    reader = PaidReader(comment_failure=failure)
    result = r.enrich(plan(budget={'comment_reads': 1}), collected(), draft(), tmp_path,
                      adapter=_free(), body_adapter=reader, **spend(tmp_path))
    assert result['evidence'][0]['source_grade'] == 'note_body'
    assert not [item for item in result['evidence'] if item['source_grade'] == 'note_comment']
    settles = [row for row in ledger_rows(tmp_path) if row['kind'] == 'settle']
    assert settles[-1]['actual_cny'] == '0' and settles[-1]['billed'] is False
    assert c.remaining(ledger_rows(tmp_path), envelope()) == Decimal('4.85')


def test_a_dry_comment_allowance_does_not_follow_two_targets(tmp_path):
    """comment_reads counts pages, not targets: the second finalist waits for budget."""
    gap_text = '\n'.join([
        'CANDIDATE|C01|research|兼容表达可能让选购产生困惑|E1,E2|-|标题不足以判断具体原因',
        'GAP|C01|E1,E2|未读正文，无法区分并对照两款表达|对照可改变入选与边界',
        'SCOPE|本轮限定笔芯相关查询；仅有标题，尚不能形成精选判断。'])
    reader = PaidReader()
    result = r.enrich(plan(budget={'comment_reads': 1}), _collected_two(),
                      e.parse_protocol(gap_text), tmp_path,
                      adapter=_free(), body_adapter=reader, **spend(tmp_path))
    assert len(reader.detail_urls) == 2 and reader.comment_ids == [NOTE_ID]
    assert len([item for item in result['evidence']
                if item['source_grade'] == 'note_comment']) == 1


def _collected_two():
    return {'evidence': [dict(EVIDENCE[0]), dict(EVIDENCE[0], id='E2', source_id='n2',
                                 url='https://www.xiaohongshu.com/explore/n2')],
            'collection': {'status': 'complete', 'errors': []},
            'external_context': [], 'ledger': []}


def _free():
    class FreeReader:
        configured = True

        def detail(self, url):
            return {'normalized_note': {'url': url, 'raw': {'NoteId': NOTE_ID, 'Content': '片段'}}}

    return FreeReader()
