"""JustOneAPI documented note read; no automatic retries or logging of token URLs."""
import os
import re
from urllib.parse import urlsplit

import httpx

from insightbot.signal_desk import grades

# search-note/v4 is the mobile-app flow: accurate time filtering, ~1/4 the response
# body of v2, and it exposes total/has_more. v2's noteTime filter is documented as
# imprecise, so v4 is the only version suitable for time-window research.
SEARCH_URL = 'https://api.justoneapi.com/api/xiaohongshu/search-note/v4'
DETAIL_URL = 'https://api.justoneapi.com/api/xiaohongshu/get-note-detail/v1'
COMMENT_URL = 'https://api.justoneapi.com/api/xiaohongshu/get-note-comment/v2'

# v4 renamed the v2 params: sort -> sortType, noteTime -> timeFilter, noteType '_0' -> 'ALL'.
VALID_TIME_FILTERS = ('ONE_DAY', 'ONE_WEEK', 'HALF_YEAR')
# Comment sorts per the endpoint contract (2026-10-12 schema check). The vendor advises
# `latest` by default and `normal` as the fallback when `latest` returns nothing.
COMMENT_SORTS = ('normal', 'latest', 'like_count')


class ProviderError(RuntimeError):
    """A source failure safe to show, carrying whatever the vendor actually told us.

    ``code`` is the business code from the response body and ``http_status`` the transport
    status when there was one. They exist because the spend ledger settles a failed call
    at zero *by code* and would otherwise have to guess: recovering the code by parsing
    the message works exactly until the message is reworded, and then a failed call
    silently keeps holding budget it never used.

    Neither field may carry the token — these messages reach operators.
    """

    def __init__(self, message, *, code=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def _auth_token(token=None):
    """Resolve the token in one place.

    An injected token and the environment must never disagree: if the adapter reports
    itself configured while the request reads the environment instead, the failure
    surfaces as an unrelated "not configured" error much later.
    """
    value = token if token is not None else os.environ.get('JUSTONEAPI_TOKEN', '')
    return str(value or '').strip()


def justone_note_detail(note_id: str, token=None):
    token = _auth_token(token)
    if not token:
        raise ValueError('JUSTONEAPI_TOKEN is not configured')
    try:
        response = httpx.get(DETAIL_URL,
                             params={'token': token, 'noteId': note_id}, timeout=45, follow_redirects=False)
        if response.status_code != 200:
            raise ProviderError(f'JustOneAPI HTTP {response.status_code}',
                                http_status=response.status_code)
        result = response.json()
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('JustOneAPI request failed or outcome uncertain; no automatic retry') from None
    if result.get('code') != 0:
        raise ProviderError('JustOneAPI business error '
                            f'{result.get("code")}; check authentication, permission or balance',
                            code=result.get('code'))
    return result


def justone_note_comment(note_id: str, token=None, *, sort: str = 'latest', cursor=None):
    """One page of a note's comments, verified against a real response 2026-10-12.

    The response shape is a dict (``data.comments[]`` ＋ ``comment_count`` ＋ cursor) —
    a third shape, different from both detail (``data[0].note_list[0]``) and search
    (``data.notes[]``). Callers normalise through :func:`comments_to_evidence`, which
    fails loudly on anything else.
    """
    token = _auth_token(token)
    if not token:
        raise ValueError('JUSTONEAPI_TOKEN is not configured')
    if sort not in COMMENT_SORTS:
        raise ValueError('Invalid comment sort')
    params = {'token': token, 'noteId': str(note_id).strip(), 'sort': sort}
    if cursor:
        params['lastCursor'] = str(cursor)
    try:
        response = httpx.get(COMMENT_URL, params=params, timeout=45, follow_redirects=False)
        if response.status_code != 200:
            raise ProviderError(f'JustOneAPI HTTP {response.status_code}',
                                http_status=response.status_code)
        result = response.json()
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('JustOneAPI request failed or outcome uncertain; no automatic retry') from None
    if result.get('code') != 0:
        raise ProviderError('JustOneAPI business error '
                            f'{result.get("code")}; check authentication, permission or balance',
                            code=result.get('code'))
    data = result.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('comments'), list):
        raise ProviderError('JustOneAPI comment schema changed')
    return result


def justone_search(keyword: str, note_time: str | None = None, token=None):
    if not keyword.strip():
        raise ValueError('Keyword required')
    if note_time not in (None, 'ALL', *VALID_TIME_FILTERS):
        raise ValueError('Invalid note time')
    token = _auth_token(token)
    if not token:
        raise ValueError('JUSTONEAPI_TOKEN is not configured')
    params = {'token': token, 'keyword': keyword, 'page': 1, 'sortType': 'general', 'noteType': 'ALL'}
    if note_time and note_time != 'ALL':
        params['timeFilter'] = note_time
    try:
        response = httpx.get(SEARCH_URL, params=params, timeout=120, follow_redirects=False)
        if response.status_code != 200:
            raise ProviderError(f'JustOneAPI HTTP {response.status_code}',
                                http_status=response.status_code)
        result = response.json()
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('JustOneAPI request failed or outcome uncertain; no automatic retry') from None
    if result.get('code') != 0:
        raise ProviderError('JustOneAPI business error '
                            f'{result.get("code")}; inspect account permission/balance',
                            code=result.get('code'))
    data = result.get('data')
    # v4 nests the page under data.notes; a page with zero hits still returns an empty list.
    if not isinstance(data, dict) or not isinstance(data.get('notes'), list):
        raise ProviderError('JustOneAPI search schema changed; not a zero-result search')
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


# ---------------------------------------------------------------------------
# Note body: the only path in the pipeline that can yield grades.note_body.
#
# Measured 2026-10-11 against get-note-detail/v1 (note 6ac8bdee00000000140016dc):
#   data                -> list, length 1        (search returns data.notes[] instead)
#   data[0].note_list   -> list, length 1        (61 fields on the note)
#   note.desc           -> the note text
# The two endpoints disagree on shape, so both readers fail loudly on anything
# unexpected. A guess here would misfile a 60-char summary as a body, which is
# exactly the error the grade vocabulary exists to prevent.
#
# Cost note: that response is ~80k characters while the note text is a few hundred.
# Detail is a heavy payload with a small text yield, so bodies are read only for
# finalists (METHODOLOGY §6.3), never for a whole search page.

NOTE_ID_RE = re.compile(r'/(?:explore|discovery/item)/([A-Za-z0-9]+)')


def note_id_from_url(value):
    """Read a note id from an explore URL, or accept a bare 24-character id."""
    raw = str(value or '').strip()
    if re.fullmatch(r'[0-9a-fA-F]{24}', raw):
        return raw
    match = NOTE_ID_RE.search(urlsplit(raw).path) or NOTE_ID_RE.search(raw)
    if not match:
        raise ValueError('cannot read a note id from this URL')
    return match.group(1)


def detail_note(response, *, url=''):
    """Return the note object from a detail response, or raise on any other shape.

    When ``url`` is given it must agree with the returned note id: a body filed
    against the wrong source id is worse than no body at all.
    """
    data = response.get('data') if isinstance(response, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise RuntimeError('JustOneAPI detail schema changed: data is not a non-empty list')
    notes = data[0].get('note_list')
    if not isinstance(notes, list) or not notes or not isinstance(notes[0], dict):
        raise RuntimeError('JustOneAPI detail schema changed: note_list is not a non-empty list')
    note = notes[0]
    note_id = str(note.get('id') or '').strip()
    if not note_id:
        raise RuntimeError('JustOneAPI detail schema changed: note has no id')
    if url and note_id_from_url(url) != note_id:
        raise RuntimeError('JustOneAPI returned a different note than requested')
    return note


def detail_to_evidence(response, *, url, query=''):
    """Normalise a detail response into one evidence item graded ``note_body``.

    Returns ``None`` when the note carries no text: an empty body is not a body,
    and grading it as one would let a card cite nothing.
    """
    from datetime import datetime, timezone
    note = detail_note(response, url=url)
    desc = str(note.get('desc') or '').strip()
    if not desc:
        return None
    title = str(note.get('title') or desc[:80]).strip()
    stamp = note.get('time')
    published = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if isinstance(stamp, (int, float)) else None
    return {'provider': 'JustOneAPI', 'platform': 'xiaohongshu', 'url': url,
            'source_id': str(note.get('id')), 'title': title,
            'excerpt': desc[:12000], 'desc_length': len(desc), 'body_verified': True,
            'published_at': published, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'query': query, 'ip_location': note.get('ip_location'),
            # get-note-detail returns the note's own text, so this is the one grade
            # that is not summary-only and can carry a deliverable claim.
            'source_grade': 'note_body',
            'limitation': ("Note body retrieved via get-note-detail; the text is the author's own "
                           "account and is not independently verified, and one note is not prevalence.")}


# ---------------------------------------------------------------------------
# Comment thread: the L1 comment layer (METHODOLOGY §2.2) — objections, repurchase
# signals, unanswered questions. Shape verified against a real 2026-10-12 response
# (note 6ac8bdee00000000140016dc): data is a dict with comments[] (10 per page),
# comment_count / comment_count_l1, has_more and a JSON-string cursor — a third shape,
# different from detail and search. Fail closed on anything else.

COMMENT_PAGE_LIMIT = 20
COMMENT_TEXT_LIMIT = 8000


def _comment_line(comment, depth=0):
    """One readable line per comment; replies keep one indent level."""
    user = comment.get('user') if isinstance(comment.get('user'), dict) else {}
    who = str(user.get('nickname') or user.get('red_id') or '').strip() or '匿名用户'
    where = str(comment.get('ip_location') or '').strip()
    text = str(comment.get('content') or '').strip().replace('\n', ' ')
    line = f'{"　" * depth}{who}（{where or "属地未知"}）：{text}'
    likes = comment.get('like_count')
    if isinstance(likes, (int, float)) and likes:
        line += f'［赞{int(likes)}］'
    return line


def comments_to_evidence(response, *, url='', query='', note_title=''):
    """Normalise one comment page into one evidence item graded ``note_comment``.

    One item per page, not one per comment: the unit of evidence here is the thread —
    objections and replies only read sensibly together. Returns ``None`` for a page
    with no comments, because an empty comment section is not a comment thread and
    grading it as one would let a card cite nothing.
    """
    from datetime import datetime, timezone
    data = response.get('data') if isinstance(response, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get('comments'), list):
        raise RuntimeError('JustOneAPI comment schema changed: data.comments missing')
    comments = [item for item in data['comments'] if isinstance(item, dict)]
    if not comments:
        return None
    note_ids = {str(item.get('note_id') or '').strip() for item in comments}
    note_ids.discard('')
    if len(note_ids) != 1:
        raise RuntimeError('JustOneAPI comment schema changed: comments span several notes')
    note_id = note_ids.pop()
    if url and note_id_from_url(url) != note_id:
        raise RuntimeError('JustOneAPI returned comments for a different note than requested')
    lines = []
    for comment in comments[:COMMENT_PAGE_LIMIT]:
        lines.append(_comment_line(comment))
        for reply in (comment.get('sub_comments') or []):
            if isinstance(reply, dict):
                lines.append(_comment_line(reply, depth=1))
    thread = '\n'.join(lines)[:COMMENT_TEXT_LIMIT]
    stamps = [item.get('time') for item in comments if isinstance(item.get('time'), (int, float))]
    latest = (datetime.fromtimestamp(max(stamps), timezone.utc).isoformat()
              if stamps else None)
    total = data.get('comment_count')
    title = f'{str(note_title or "").strip() or "笔记"} · 评论样本（最新一页）'
    return {'provider': 'JustOneAPI', 'platform': 'xiaohongshu', 'url': url,
            'source_id': note_id, 'title': title, 'excerpt': thread,
            'desc_length': len(thread), 'body_verified': True,
            'latest_comment_at': latest, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'query': query,
            'comment_total': total if isinstance(total, int) else None,
            'comments_returned': min(len(comments), COMMENT_PAGE_LIMIT),
            'has_more': bool(data.get('has_more')),
            # get-note-comment returns other people's words in full: real text, but the
            # latest page of one note's comment section is a sample of vocal commenters,
            # never a representative read of the audience.
            'source_grade': 'note_comment',
            'limitation': ('评论区样本为该笔记最新一页评论（latest 排序）；评论者是个体的声音，不构成'
                           '代表性人群样本；昵称与IP属地为平台自报，未经核实。')}


class JustOneApiAdapter:
    """Read note bodies through JustOneAPI.

    This is the only adapter in the pipeline that can produce ``grades.note_body``:
    the 千瓜 detail endpoint returns no content field at all (measured 2026-10-11),
    so a pipeline wired to 千瓜 alone can never support a deliverable card. That is
    the concrete reason this adapter exists, not a preference between vendors.

    Same surface as ``QianguaAdapter`` (``configured``/``auth``/``search``/``detail``)
    so the two are interchangeable wherever a reader is injected. The token comes
    from the environment only and is never logged, echoed, or written to disk.
    """

    TOKEN_ENV = 'JUSTONEAPI_TOKEN'

    def __init__(self, token=None):
        self.token = (token if token is not None else os.environ.get(self.TOKEN_ENV, '')).strip()

    @property
    def configured(self):
        """False when no token is set; callers must then fall back, not fail."""
        return bool(self.token)

    def auth(self):
        if not self.configured:
            raise RuntimeError(f'{self.TOKEN_ENV} is not configured')
        return True

    def search(self, query, *, page=1, page_size=10):
        """Present for interface parity. Retrieval still runs through 千瓜; see
        ``research_v2.collect`` for why that split is deliberate."""
        return justone_search(query['keyword'], query.get('time_filter'), self.token)

    def detail(self, url):
        return justone_note_detail(note_id_from_url(url), self.token)

    def comments(self, note_id, *, sort='latest', cursor=None):
        """One page of a note's comment thread. Only this reader offers comments:
        千瓜's comment search was excluded by the narrow-quota rules (§6.2)."""
        return justone_note_comment(note_id, self.token, sort=sort, cursor=cursor)
