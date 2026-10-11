"""JustOneAPI price data and pre-call quoting.

Prices live in a versioned CSV exported from the vendor dashboard, not in code. The
reason is that a cost model is only reproducible if the prices it used are pinned: once
a sheet is edited in place, last quarter's estimate can no longer be recomputed. Each
export therefore lands as its own dated file and quotes carry the export date.

Facts this module encodes (measured 2026-10-11, see docs/signal-desk/JUSTONEAPI-ASSETS.md):

* 296 endpoints across 35 platforms, ¥0.05—¥1.50 per request. The xiaohongshu search and
  detail endpoints we use cost ¥0.15—¥0.20.
* Prices are per **successful** request. Officially stated by the vendor: only ``code=0``
  is billed, every other business code (100/301/302/303/400/500/600/601/602) is free.
  See :data:`costcontrol.BILLING_CODES` for the full table.
* Two endpoints are listed as 未开通 with no price. They resolve to ``unit_price=None``
  and :meth:`Quote.chargeable` is False, so a caller cannot silently treat them as free.

Quoting deliberately never guesses. An endpoint that is not in the table is unknown,
not free — see costcontrol.authorize, which denies rather than estimating zero.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TABLE = ROOT / 'config' / 'pricing' / 'justoneapi-pricing-20261011.csv'

# Export metadata, kept next to the loader so a quote can always name its own basis.
EXPORTED_AT = '2026-10-11T15:30:30+08:00'
EXPORTED_FROM = 'dashboard.justoneapi.com 价目表导出（筛选：所有接口，296 条）'
CURRENCY = 'CNY'

# Provenance. The vendor publishes NO public price list: docs.justoneapi.com/zh/usage says
# prices are only visible after logging in, and the dashboard pricing route redirects an
# anonymous request to the login page. The dashboard export is therefore the one official
# source, and pinning it to a dated file is the only way to keep a cost model reproducible.
PRICE_SOURCE_URL = 'https://dashboard.justoneapi.com/zh/dashboard/pricing'
DOCS_USAGE_URL = 'https://docs.justoneapi.com/zh/usage'
API_BASE_URL = 'https://api.justoneapi.com'

PERMISSION_ALLOWED = 'allowed'
PERMISSION_UNAVAILABLE = 'unavailable'


def normalize_id(value) -> str:
    """Reduce any endpoint spelling to one join key.

    ``/api/xiaohongshu/search-note/v4`` and ``xiaohongshu.search_note_v4`` both become
    ``xiaohongshu_search_note_v4``. The two spellings must be joined without inventing
    ids: the price sheet lists REST paths, while MCP call_endpoint takes dot-notation
    ids whose version suffixes do not always correspond.
    """
    text = str(value or '').strip().lower().lstrip('/')
    if text.startswith('api/'):
        text = text[4:]
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', text)).strip('_')


@dataclass(frozen=True)
class Quote:
    """What one request to an endpoint costs, or why it cannot be priced."""
    key: str
    endpoint_path: str = ''
    platform: str = ''
    unit_price: Decimal | None = None
    permission: str = ''
    known: bool = False
    table: str = ''

    @property
    def chargeable(self) -> bool:
        """True only when the endpoint is priced AND permitted. Unknown is not free."""
        return (self.unit_price is not None
                and self.permission == PERMISSION_ALLOWED)

    def cost(self, calls: int = 1) -> Decimal:
        if calls < 0:
            raise ValueError('calls must not be negative')
        if not self.chargeable:
            raise ValueError(f'{self.key or "unknown endpoint"} cannot be priced: '
                             f'permission={self.permission or "unknown"}, '
                             f'unit_price={self.unit_price}')
        return self.unit_price * calls


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        return None


@lru_cache(maxsize=8)
def price_table(path: str | Path = DEFAULT_TABLE) -> dict[str, Quote]:
    """Load a price sheet into ``{normalized_id: Quote}``.

    Raises ``ValueError`` if two rows collapse onto the same key: a silent collision
    would let one endpoint inherit another's price, which is exactly the kind of error
    that stays invisible until an invoice arrives.
    """
    table = Path(path)
    if not table.is_file():
        raise FileNotFoundError(f'price table missing: {table}')
    entries: dict[str, Quote] = {}
    with table.open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            path_value = (row.get('endpoint_path') or '').strip()
            if not path_value:
                continue
            key = normalize_id(path_value)
            if key in entries:
                raise ValueError(f'price table collision on {key!r}: '
                                 f'{entries[key].endpoint_path!r} vs {path_value!r}')
            entries[key] = Quote(key=key, endpoint_path=path_value,
                                 platform=(row.get('platform') or '').strip(),
                                 unit_price=_to_decimal(row.get('price_cny') or ''),
                                 permission=(row.get('permission') or '').strip(),
                                 known=True, table=table.name)
    return entries


def quote(endpoint: str | None, path: str | Path = DEFAULT_TABLE) -> Quote:
    """Price one endpoint by REST path or MCP endpoint id. Unknown stays unknown."""
    key = normalize_id(endpoint)
    entries = price_table(path)
    found = entries.get(key)
    if found is not None:
        return found
    return Quote(key=key, known=False, table=Path(path).name)


def price_of(endpoint: str | None, path: str | Path = DEFAULT_TABLE) -> Decimal | None:
    """Unit price, or ``None`` when the endpoint is unpriced or not permitted."""
    found = quote(endpoint, path)
    return found.unit_price if found.chargeable else None


def cheapest(endpoints, path: str | Path = DEFAULT_TABLE):
    """Cheapest chargeable option among equivalent endpoints, for version alternates."""
    quoted = [quote(e, path) for e in endpoints]
    priced = [q for q in quoted if q.chargeable]
    return min(priced, key=lambda q: q.unit_price) if priced else None


def table_summary(path: str | Path = DEFAULT_TABLE) -> dict:
    """Counts used in reports, so a doc figure and a live quote never disagree."""
    entries = price_table(path)
    prices = {}
    for entry in entries.values():
        if entry.chargeable:
            prices[entry.unit_price] = prices.get(entry.unit_price, 0) + 1
    return {'endpoints': len(entries),
            'platforms': len({e.platform for e in entries.values()}),
            'unpriced': sum(1 for e in entries.values() if not e.chargeable),
            'by_price': dict(sorted(prices.items()))}
