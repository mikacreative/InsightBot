"""JustOneAPI documented note read; no automatic retries or logging of token URLs."""
import os
import httpx

from insightbot.signal_desk import grades

# search-note/v4 is the mobile-app flow: accurate time filtering, ~1/4 the response
# body of v2, and it exposes total/has_more. v2's noteTime filter is documented as
# imprecise, so v4 is the only version suitable for time-window research.
SEARCH_URL = 'https://api.justoneapi.com/api/xiaohongshu/search-note/v4'
DETAIL_URL = 'https://api.justoneapi.com/api/xiaohongshu/get-note-detail/v1'

# v4 renamed the v2 params: sort -> sortType, noteTime -> timeFilter, noteType '_0' -> 'ALL'.
VALID_TIME_FILTERS = ('ONE_DAY', 'ONE_WEEK', 'HALF_YEAR')


def justone_note_detail(note_id: str):
    token = os.environ.get('JUSTONEAPI_TOKEN', '')
    if not token:
        raise ValueError('JUSTONEAPI_TOKEN is not configured')
    try:
        response = httpx.get(DETAIL_URL,
                             params={'token': token, 'noteId': note_id}, timeout=45, follow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f'JustOneAPI HTTP {response.status_code}')
        result = response.json()
    except Exception:
        raise RuntimeError('JustOneAPI request failed or outcome uncertain; no automatic retry') from None
    if result.get('code') != 0:
        code = result.get('code')
        raise RuntimeError(f'JustOneAPI business error {code}; check authentication, permission or balance')
    return result


def justone_search(keyword: str, note_time: str | None = None):
    if not keyword.strip():
        raise ValueError('Keyword required')
    if note_time not in (None, 'ALL', *VALID_TIME_FILTERS):
        raise ValueError('Invalid note time')
    token = os.environ.get('JUSTONEAPI_TOKEN', '')
    if not token:
        raise ValueError('JUSTONEAPI_TOKEN is not configured')
    params = {'token': token, 'keyword': keyword, 'page': 1, 'sortType': 'general', 'noteType': 'ALL'}
    if note_time and note_time != 'ALL':
        params['timeFilter'] = note_time
    try:
        response = httpx.get(SEARCH_URL, params=params, timeout=120, follow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError('HTTP failure')
        result = response.json()
    except Exception:
        raise RuntimeError('JustOneAPI request failed or outcome uncertain; no automatic retry') from None
    if result.get('code') != 0:
        raise RuntimeError(f"JustOneAPI business error {result.get('code')}; inspect account permission/balance")
    data = result.get('data')
    # v4 nests the page under data.notes; a page with zero hits still returns an empty list.
    if not isinstance(data, dict) or not isinstance(data.get('notes'), list):
        raise RuntimeError('JustOneAPI search schema changed; not a zero-result search')
    return {'provider': 'JustOneAPI', 'endpoint': 'search-note/v4', 'query': keyword, 'page': 1,
            'sort': 'general', 'note_time': note_time,
            'limitations': ('One search page. desc is a truncated summary (measured <=60 chars, not the note '
                            'body) - retrieve get-note-detail before quoting full text. Time filter is accurate '
                            'on v4; raw response requires evidence normalization.'),
            'raw': result}


def search_to_input(result, brand, question):
    """Schema verified against actual 2026-10-11 search-note/v4 responses (77-note sample)."""
    from datetime import datetime, timezone
    data = result['raw'].get('data')
    if not isinstance(data, dict) or not isinstance(data.get('notes'), list):
        raise RuntimeError('JustOneAPI search schema changed; not a zero-result search')
    notes = data['notes']
    evidence = []
    skipped_non_note = 0
    for note in notes:
        if not isinstance(note, dict):
            raise RuntimeError('JustOneAPI note schema changed')
        if note.get('model_type') not in (None, 'note'):
            skipped_non_note += 1
            continue
        note_id = note.get('id')
        if not note_id:
            raise RuntimeError('JustOneAPI note schema changed')
        excerpt = str(note.get('desc') or note.get('title') or '').strip()
        if not excerpt:
            raise RuntimeError('JustOneAPI note has no usable text; enrich detail before import')
        stamp = note.get('timestamp')
        published = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if isinstance(stamp, (float, int)) else None
        evidence.append({'platform': 'xiaohongshu', 'source_id': str(note_id), 'provider': 'JustOneAPI',
                         'url': 'https://www.xiaohongshu.com/explore/' + str(note_id),
                         'title': str(note.get('title') or excerpt[:80]), 'excerpt': excerpt,
                         'desc_length': len(excerpt), 'body_verified': False,
                         'published_at': published, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                         'query': result['query'],
                         # A search page returns note_segment, never note_body: the measured desc is cut
                         # at 60 characters, so it ranks with titles and cannot support a full claim.
                         'source_grade': 'note_segment',
                         'limitation': ('Truncated search summary (measured <=60 chars), not the note body; '
                                        'author identity and full text unverified; not population prevalence.')})
    return {'brief': {'brand': brand, 'question': question, 'time_window': result.get('note_time') or 'unfiltered'},
            'evidence': evidence, 'collection': {**{k: v for k, v in result.items() if k != 'raw'},
                                                 'returned_items': len(notes), 'note_count': len(evidence),
                                                 'skipped_non_note': skipped_non_note,
                                                 'has_more': data.get('has_more'), 'total': data.get('total')}}
