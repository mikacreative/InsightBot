"""External background context: RSS headlines and web search snippets.

Context is background for the editor to interpret signals, never evidence: items carry no evidence
id, cannot be quoted, cannot appear in a figure and cannot be cited as support for a card.
Every fetch is best-effort; a failed feed or search is recorded and never fails a run.
"""
from __future__ import annotations

import calendar
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from insightbot.safe_http import safe_get, UnsafeURL

RSS_FETCH_TIMEOUT_S = 15
RSS_LIMIT = 12
SEARCH_LIMIT = 5
SNIPPET_LIMIT = 240


def load_context_config(path: str | None = None) -> dict:
    """Read {rss: [...], search: {...}}; returns {} when nothing is configured."""
    path = path or os.environ.get('SIGNAL_DESK_CONTEXT_CONFIG', '')
    if not str(path).strip():
        return {}
    file = Path(path)
    if not file.is_file():
        raise ValueError('Signal Desk context config not found')
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        raise ValueError('Signal Desk context config is not valid JSON') from None
    if not isinstance(data, dict):
        raise ValueError('Signal Desk context config must be an object')
    feeds = data.get('rss', [])
    search = data.get('search') or {}
    if not isinstance(feeds, list) or not isinstance(search, dict):
        raise ValueError('Signal Desk context config: rss must be a list, search an object')
    kept = []
    for feed in feeds:
        if isinstance(feed, dict) and str(feed.get('url', '')).strip():
            kept.append({'id': str(feed.get('id', '')).strip() or str(feed['url'])[:80],
                         'name': str(feed.get('name', '')).strip(),
                         'url': str(feed['url']).strip(),
                         'tags': [str(t).strip() for t in feed.get('tags', []) if str(t).strip()]})
    return {'rss': kept, 'search': search}


def _clean(text: str, limit: int = SNIPPET_LIMIT) -> str:
    import re
    from html import unescape
    value = unescape(str(text or ''))
    value = re.sub(r'<[^>]+>', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip()
    return value if len(value) <= limit else value[:limit].rstrip(' ，,.;；。') + '...'


def _entry_summary(entry) -> str:
    for candidate in (getattr(entry, 'summary', ''), getattr(entry, 'description', '')):
        cleaned = _clean(candidate)
        if cleaned:
            return cleaned
    for item in (getattr(entry, 'content', None) or []):
        cleaned = _clean(item.get('value', '') if isinstance(item, dict) else getattr(item, 'value', ''))
        if cleaned:
            return cleaned
    return ''


def _published(entry) -> str | None:
    stamp = getattr(entry, 'published_parsed', None) or getattr(entry, 'updated_parsed', None)
    if not stamp:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc).isoformat()
    except (OverflowError, ValueError, OSError):
        return None


def fetch_rss_context(feeds: list[dict], *, limit: int = RSS_LIMIT) -> dict:
    """Fetch recent RSS entries across feeds. Records per-feed errors; never raises."""
    import feedparser
    items, errors = [], []
    for feed in feeds:
        if len(items) >= limit:
            break
        url, name = feed['url'], feed.get('name') or feed.get('id') or feed['url']
        try:
            response = safe_get(url, timeout=RSS_FETCH_TIMEOUT_S,
                                headers={'User-Agent': 'InsightBot-SignalDesk/0.4.0'})
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            for entry in parsed.entries:
                if len(items) >= limit:
                    break
                title = _clean(getattr(entry, 'title', ''), 160)
                link = str(getattr(entry, 'link', '')).strip()
                if not title or not link:
                    continue
                items.append({'title': title, 'link': link, 'source': name, 'kind': 'rss',
                              'published_at': _published(entry), 'snippet': _entry_summary(entry)})
        except (UnsafeURL, OSError, ValueError) as error:
            errors.append({'source': name, 'url': url, 'error': str(error)[:200]})
        except Exception as error:
            errors.append({'source': name, 'url': url, 'error': f'{type(error).__name__}: {str(error)[:160]}'})
    return {'items': items, 'errors': errors}


def _search_ddgs(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS
    found = []
    with DDGS() as ddgs:
        for result in ddgs.text(query, max_results=max_results):
            link, title = str(result.get('href', '')).strip(), str(result.get('title', '')).strip()
            if not link or not title:
                continue
            found.append({'title': _clean(title, 160), 'link': link, 'source': 'web search',
                          'kind': 'search', 'published_at': None,
                          'snippet': _clean(result.get('body', '')), 'query': query})
    return found


def search_web_context(search: dict, *, queries: list[str], limit: int = SEARCH_LIMIT) -> dict:
    """Search the public web for background. Records errors; never raises."""
    items, errors = [], []
    if not search.get('enabled') or not queries:
        return {'items': items, 'errors': errors}
    provider = str(search.get('provider', 'duckduckgo')).strip().lower()
    max_results = int(search.get('max_results', limit))
    for query in queries[:5]:
        if len(items) >= limit:
            break
        try:
            if provider != 'duckduckgo':
                raise ValueError(f'Unsupported search provider: {provider}')
            items.extend(_search_ddgs(query, max_results)[: max(0, limit - len(items))])
        except Exception as error:
            errors.append({'query': query, 'provider': provider, 'error': f'{type(error).__name__}: {str(error)[:160]}'})
    return {'items': items, 'errors': errors}


def _queries_from_brief(brief: dict, search: dict) -> list[str]:
    explicit = [str(q).strip() for q in search.get('queries', []) if str(q).strip()]
    if explicit:
        return explicit
    brand = str(brief.get('brand', '')).strip()
    topics = str(brief.get('topics', '')).strip()
    keyword = str(brief.get('keyword', '')).strip()
    derived = [f'{brand} {part.strip()}'.strip() for part in topics.replace('、', ',').split(',') if part.strip()][:2]
    if not derived and keyword:
        derived = [f'{brand} {keyword}'.strip()]
    return derived


def collect_context(config: dict, brief: dict) -> tuple[list[dict], dict]:
    """Gather external background for a run. Returns (items, collection metadata)."""
    feeds, search = (config or {}).get('rss', []), (config or {}).get('search', {})
    rss = fetch_rss_context(feeds) if feeds else {'items': [], 'errors': []}
    queries = _queries_from_brief(brief or {}, search)
    web = search_web_context(search, queries=queries) if search.get('enabled') else {'items': [], 'errors': []}
    items = (rss['items'] + web['items'])[:24]
    meta = {'rss_feeds': len(feeds), 'rss_items': len(rss['items']), 'search_queries': queries if web['items'] or web['errors'] else [],
            'search_items': len(web['items']), 'errors': (rss['errors'] + web['errors'])[:10],
            'limitations': ['External context is unverified background (headlines and snippets), not evidence: '
                            'it is never quoted, cited or counted, and it is not representative of any population.']}
    return items, meta
