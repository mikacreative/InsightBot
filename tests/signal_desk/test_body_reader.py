"""The note-body reader: the only path in the pipeline to ``grades.note_body``.

The shapes below are the ones measured on 2026-10-11 against the live endpoint, because
the two JustOneAPI endpoints disagree: search returns ``data.notes[]``, detail returns a
*list* holding ``note_list``. A reader that accepted either shape would silently file a
60-character search summary as a full body, which is the exact failure the grade
vocabulary exists to prevent.
"""
import pytest

from insightbot.signal_desk import grades, providers

NOTE_ID = '6ac8bdee00000000140016dc'
NOTE_URL = f'https://www.xiaohongshu.com/explore/{NOTE_ID}'
DETAIL = {'code': 0, 'data': [{'model_type': 'note', 'track_id': '', 'comment_list': [], 'note_list': [{
    'api_upgrade': -1, 'id': NOTE_ID, 'type': 'normal', 'title': '👀Merodi新品手办！（全图鉴）',
    'desc': '#点心时间 今天开箱，手感比上一代好太多。', 'time': 1791540718, 'ip_location': '湖南',
    'liked_count': 2267, 'view_count': 0}]}]}


def test_note_id_reads_every_supported_form():
    assert providers.note_id_from_url(NOTE_URL) == NOTE_ID
    assert providers.note_id_from_url(f'https://www.xiaohongshu.com/discovery/item/{NOTE_ID}') == NOTE_ID
    assert providers.note_id_from_url(NOTE_ID) == NOTE_ID
    with pytest.raises(ValueError):
        providers.note_id_from_url('https://www.xiaohongshu.com/user/profile/620a08060000000010005e4c')


def test_detail_reader_rejects_the_search_shape():
    """``data.notes[]`` is the search shape; accepting it files a summary as a body."""
    with pytest.raises(RuntimeError, match='data is not a non-empty list'):
        providers.detail_note({'data': {'notes': [{'id': NOTE_ID}]}})
    with pytest.raises(RuntimeError, match='note_list'):
        providers.detail_note({'data': [{'model_type': 'note'}]})
    with pytest.raises(RuntimeError, match='note_list'):
        providers.detail_note({'data': [{'note_list': []}]})


def test_detail_reader_refuses_a_note_it_did_not_ask_for():
    with pytest.raises(RuntimeError, match='different note'):
        providers.detail_note(DETAIL, url='https://www.xiaohongshu.com/explore/000000000000000000000001')


def test_a_retrieved_body_is_graded_note_body():
    item = providers.detail_to_evidence(DETAIL, url=NOTE_URL, query='潮玩')
    assert item['source_grade'] == 'note_body'
    assert grades.is_body(item['source_grade']) and not grades.summary_only(item['source_grade'])
    assert item['provider'] == 'JustOneAPI' and item['source_id'] == NOTE_ID
    assert item['excerpt'].startswith('#点心时间')
    assert item['desc_length'] == len(item['excerpt']) and item['body_verified'] is True


def test_a_note_without_text_is_not_a_body():
    """An empty desc is not a body; grading it as one would let a card cite nothing."""
    empty = {'code': 0, 'data': [{'note_list': [{'id': NOTE_ID, 'title': '只有标题'}]}]}
    assert providers.detail_to_evidence(empty, url=NOTE_URL) is None


def test_adapter_says_whether_it_can_read_at_all(monkeypatch):
    monkeypatch.delenv(providers.JustOneApiAdapter.TOKEN_ENV, raising=False)
    assert providers.JustOneApiAdapter().configured is False
    assert providers.JustOneApiAdapter(token='   ').configured is False
    assert providers.JustOneApiAdapter(token='secret').configured is True
    with pytest.raises(RuntimeError, match=providers.JustOneApiAdapter.TOKEN_ENV):
        providers.JustOneApiAdapter().auth()


def test_the_token_never_rides_along_in_an_error(monkeypatch):
    """These errors reach operators; the token that caused them must not travel with them."""
    def boom(*args, **kwargs):
        raise OSError('connection reset')
    monkeypatch.setattr(providers.httpx, 'get', boom)
    adapter = providers.JustOneApiAdapter(token='secret-token-value')
    with pytest.raises(RuntimeError) as caught:
        adapter.detail(NOTE_URL)
    assert 'secret-token-value' not in str(caught.value)
