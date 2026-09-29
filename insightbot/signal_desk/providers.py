"""JustOneAPI documented note detail read; no automatic retries or logging of token URLs."""
import os
import httpx


def justone_note_detail(note_id: str):
    token = os.environ.get('JUSTONEAPI_TOKEN', '')
    if not token:
        raise ValueError('JUSTONEAPI_TOKEN is not configured')
    try:
        response = httpx.get('https://api.justoneapi.com/api/xiaohongshu/get-note-detail/v1',
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
    if note_time not in (None, 'ONE_DAY', 'ONE_WEEK', 'HALF_YEAR'):
        raise ValueError('Invalid note time')
    token = os.environ.get('JUSTONEAPI_TOKEN', '')
    if not token:
        raise ValueError('JUSTONEAPI_TOKEN is not configured')
    params = {'token': token, 'keyword': keyword, 'page': 1, 'sort': 'general', 'noteType': '_0'}
    if note_time: params['noteTime'] = note_time
    try:
        response = httpx.get('https://api.justoneapi.com/api/xiaohongshu/search-note/v2', params=params, timeout=120, follow_redirects=False)
        if response.status_code != 200: raise RuntimeError('HTTP failure')
        result = response.json()
    except Exception:
        raise RuntimeError('JustOneAPI request failed or outcome uncertain; no automatic retry') from None
    if result.get('code') != 0:
        raise RuntimeError(f"JustOneAPI business error {result.get('code')}; inspect account permission/balance")
    if 'data' not in result:
        raise RuntimeError('JustOneAPI response schema missing data; not a zero-result search')
    return {'provider': 'JustOneAPI', 'query': keyword, 'page': 1, 'sort': 'general', 'note_time': note_time,
            'limitations': 'One search page; time filter is imprecise; raw response requires evidence normalization.', 'raw': result}


def search_to_input(result, brand, question):
    """Schema verified through actual 2026-09-29 search-note/v2 response."""
    from datetime import datetime, timezone
    data = result['raw'].get('data')
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise RuntimeError('JustOneAPI search schema changed; not a zero-result search')
    evidence = []
    skipped_non_note = 0
    for item in data['items']:
        if item.get('model_type') != 'note':
            skipped_non_note += 1
            continue
        note = item.get('note')
        if not isinstance(note, dict) or not note.get('id'):
            raise RuntimeError('JustOneAPI note schema changed')
        excerpt = str(note.get('desc') or note.get('title') or '').strip()
        if not excerpt:
            raise RuntimeError('JustOneAPI note has no usable text; enrich detail before import')
        stamp = note.get('timestamp')
        published = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if isinstance(stamp, (float,int)) else None
        evidence.append({'platform':'xiaohongshu', 'source_id':str(note['id']), 'provider':'JustOneAPI',
                         'url':'https://www.xiaohongshu.com/explore/' + str(note['id']),
                         'title':str(note.get('title') or excerpt[:80]), 'excerpt':excerpt,
                         'published_at':published, 'retrieved_at':datetime.now(timezone.utc).isoformat(),
                         'query':result['query'], 'source_grade':'search excerpt',
                         'limitation':'One search page; date filter imprecise; identity and full body not verified; not population prevalence.'})
    return {'brief':{'brand':brand,'question':question,'time_window':result.get('note_time') or 'unfiltered'},
            'evidence':evidence, 'collection':{**{k:v for k,v in result.items() if k != 'raw'}, 'returned_items':len(data['items']), 'note_count':len(evidence), 'skipped_non_note':skipped_non_note}}
