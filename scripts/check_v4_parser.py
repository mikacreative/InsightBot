"""Offline check: feed real v4 responses (saved from 2026-10-11 MCP calls) through the
parser and the grade vocabulary. Zero API cost -- no token, no network, no billing.

Run:  python3 scripts/check_v4_parser.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from insightbot.signal_desk import grades  # noqa: E402
from insightbot.signal_desk.providers import search_to_input  # noqa: E402

BASE = Path('/Users/mikawang/.workbuddy/projects/'
            'Users-mikawang-Documents-GitHub-InsightBot-signal-desk/'
            '266e7574-c4e1-4498-a565-05cc2d640a48/tool-results')

FIXTURES = [
    ('mcp-justoneapi-call_endpoint-1791702850742-f849e7.txt', 1),
    ('mcp-justoneapi-call_endpoint-1791702881365-e6f9c6.txt', 2),
    ('mcp-justoneapi-call_endpoint-1791702891412-320a0e.txt', 3),
]


def main():
    total, produced, max_desc = 0, set(), 0
    for name, page in FIXTURES:
        path = BASE / name
        if not path.exists():
            print(f'missing fixture: {name}')
            return 1
        mcp = json.loads(path.read_text(encoding='utf-8'))
        result = {'provider': 'JustOneAPI', 'endpoint': 'search-note/v4', 'query': '泡泡玛特 新品',
                  'page': page, 'sort': 'general', 'note_time': None,
                  'raw': {'code': 0, 'data': mcp['data']}}
        payload = search_to_input(result, '泡泡玛特', '新品风向')
        ev = payload['evidence']
        total += len(ev)
        produced |= {x['source_grade'] for x in ev}
        max_desc = max([max_desc] + [x['desc_length'] for x in ev])
        if page == 1:
            col = {k: v for k, v in payload['collection'].items() if k != 'limitations'}
            print('collection:', json.dumps(col, ensure_ascii=False)[:220])
            e = ev[0]
            print('\nsample evidence:')
            for k in ('platform', 'source_id', 'provider', 'url', 'title',
                      'desc_length', 'body_verified', 'source_grade', 'published_at'):
                print(f'  {k:15}', str(e[k])[:78])
            print(f'  {"excerpt":15}', e['excerpt'][:66])
            print('  limitation     ', e['limitation'][:92])
            print()

    print(f'parsed {total} notes across {len(FIXTURES)} pages; longest desc = {max_desc} chars')
    print(f'grades produced: {produced}')

    print('\n--- evidence-grade vocabulary ---')
    print(f'  produces note_body?          {any(grades.is_body(g) for g in produced)}  (expected False: search returns summaries)')
    print(f'  all produced summary-only?   {all(grades.summary_only(g) for g in produced)}  (expected True: guard must fire)')
    print(f'  rank(note_segment) < rank(note_body)  '
          f'{grades.rank("note_segment")} < {grades.rank("note_body")}')

    print('\n--- legacy tokens resolve (stored runs keep their meaning) ---')
    for token in ('title_only', 'search_snippet', 'search excerpt', 'qiangua_body',
                  'full_text', 'rss_snippet', 'qiangua comment thread | general'):
        print(f'  {token:32} -> {grades.canonical(token):24} {grades.describe(token)}')

    print('\n--- unknown tokens fail closed ---')
    for token in ('search excerpt v9', 'note_body_v2', '', 'brand_new_vendor_field'):
        ok = (grades.rank(token) == 0 and grades.summary_only(token) is True
              and grades.is_body(token) is False)
        print(f'  {token[:32]:32} -> {grades.level(token):12} rank={grades.rank(token)} '
              f'summary_only={grades.summary_only(token)}  {"OK" if ok else "FAIL"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
