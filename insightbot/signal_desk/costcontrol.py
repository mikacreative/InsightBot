"""Spend control plane: quote before the call, deny when the budget is gone, ledger every call.

Why this exists. Two separate paths can spend the same JustOneAPI balance: this agent
calling the MCP tools, and ``providers.py`` calling the REST API with a static token.
Neither sees the other, and neither sees the vendor's number until a statement arrives.
A quoting function alone would not stop them double-spending, so the control point is a
single append-only ledger that both paths reserve against *before* they call.

Design rules, each one earned from a real failure mode:

1. **Unknown price means denied, never zero.** The 2026-10-11 defect was a grade token
   that some call sites did not recognise, so a truncated summary passed as a body. The
   same shape of bug in a billing path would silently under-estimate spend. An endpoint
   that is not in the price table, or is listed 未开通, is refused.
2. **Reserve, then settle.** Authorisation writes a reservation row first, so a retry, a
   parallel run or a second channel cannot both authorise against the same remaining
   budget. Settlement afterwards records reality without moving the reservation.
3. **The ledger is the ledger; the vendor statement is the truth.** Billing settles
   asynchronously (measured: one call showed no balance change, the next showed two
   charges), so local rows are estimates. :func:`reconcile` exists to compare them with
   an observed balance delta instead of pretending the estimates are exact.
4. **Settle by business code, not by estimate.** The vendor bills ``code=0`` only; every
   other code is free. Guessing an amount means a failed call either over-charges the
   ledger or hides a real charge. See :data:`BILLING_CODES`.
5. **Settlement releases the hold.** Rule 2 keeps a reservation counted while a call is
   in flight, but a reservation that has settled counts at what it actually cost. A call
   that failed and settled at zero therefore gives its budget back. Counting raw
   reservations forever would let a month of failed calls close an envelope that had
   spent nothing — a gate that shuts itself.

Deliberate non-goals: 千瓜 spend is a fixed annual seat cost with monthly quotas, not a
per-call charge, so it does not belong in this ledger. Only variable spend is governed.

Known gap, from the same guide: money is not the only axis. Administrators can cap
**successful requests per endpoint per day** (counted on ``Asia/Shanghai`` days, sync
requests on the day they are issued and async tasks on the day they are submitted, merged
across every token in the account). Exceeding it returns ``303`` + HTTP 429, unbilled.
:class:`Envelope` models currency only, so a plan can pass the money check and still be
refused upstream. Whether to model that second axis is an open decision, not an oversight.

Also from the guide, and the reason rule 2 is not paranoia: the vendor advises a 120s
timeout specifically to avoid "重复请求或误判错误" after network jitter. A client-timeout
retry against a call that in fact succeeded is a double charge, which is exactly what the
pre-call reservation prevents.

``research_v2.enrich`` is the one caller: before every paid body read it reserves that one
detail call, and afterwards it settles with the code the vendor returned. Nothing else in
the pipeline spends. A deployment that declares no envelope simply does not spend — the
round falls back to the free fragment reader and says so, which is why the gate lives in
the environment rather than in a caller argument (see :func:`envelope_from_env`).
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from insightbot.signal_desk import pricing

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / 'data' / 'signal-desk-spend.jsonl'

# How a machine declares that it is allowed to spend. Both live in the environment
# because the gate must be a deployment decision, not a default a caller can forget to
# pass: an unset limit means "no paid calls", which is the safe reading of silence.
SPEND_LIMIT_ENV = 'SIGNAL_DESK_SPEND_LIMIT_CNY'
SPEND_LEDGER_ENV = 'SIGNAL_DESK_SPEND_LEDGER'

# Endpoints are written as full REST paths on purpose: quoting must be exact. A fuzzy
# match on a billing path can silently attach the wrong price to a corrected endpoint name.
SEARCH_V4 = '/api/xiaohongshu/search-note/v4'
DETAIL_V1 = '/api/xiaohongshu/get-note-detail/v1'

# JustOneAPI-side planning envelope per research mode, in calls per period.
# METHODOLOGY §4 sets the total call volume for each mode (Scan 2—3, Probe 5—10,
# Frame 10—20), but those totals include 千瓜 calls, which are fixed-cost and are
# therefore absent here. These splits are a planning assumption, not a measurement.
# METHODOLOGY §5.4 caps body retrieval at the 0—3 selected notes; Probe and Frame add
# headroom for a second selection pass across a competitor set.
RECIPE_CALLS = {
    'scan': {SEARCH_V4: 1},
    'probe': {SEARCH_V4: 2, DETAIL_V1: 3},
    'frame': {SEARCH_V4: 3, DETAIL_V1: 6},
}


class BudgetDenied(Exception):
    """Raised when :func:`authorize` refuses a plan. Carries the decision for logging."""

    def __init__(self, decision: 'Decision'):
        super().__init__(f'{decision.reason}: {decision.detail}')
        self.decision = decision


# Business codes and whether they bill, transcribed from the vendor's own usage guide
# (docs.justoneapi.com/zh/usage, retrieved 2026-10-11). Only code=0 costs money.
#
# This table exists so settlement never has to guess. Before it, settle() defaulted a
# missing amount to the *reserved* amount, which silently over-charged every failed call
# and made the ledger disagree with the statement for reasons nobody could see.
BILLING_CODES = {
    0:   ('成功', True),
    100: ('Token 无效或已失效', False),
    301: ('采集失败，请重试', False),
    302: ('超出速率限制', False),
    303: ('超出每日配额', False),
    400: ('参数错误', False),
    500: ('内部服务器错误', False),
    600: ('权限不足', False),
    601: ('账户余额不足', False),
    602: ('TOKEN 限额超限', False),
}
BILLING_CODES_VERSION = 'justoneapi-usage-20261011'


def code_meaning(code) -> str:
    """Human meaning of a business code, or a marker when it is not in the table."""
    entry = BILLING_CODES.get(code)
    return entry[0] if entry else f'未知业务码 {code}'


def is_billed(code) -> bool:
    """Whether a business code costs money.

    Fail-closed in the *opposite* direction from :mod:`pricing`, and deliberately so.
    An unknown price is refused because spending blind is the risk. An unknown billing
    code is treated as **charged** because under-counting spend is the risk. Both errors
    point the same way: never quietly lose money. Settling an unexpected code is then
    visible as a variance in :func:`reconcile`, not as a free call.
    """
    entry = BILLING_CODES.get(code)
    return entry[1] if entry else True


@dataclass(frozen=True)
class Envelope:
    """A spend ceiling for one scope in one period, e.g. one brand in one month."""
    scope: str
    period: str
    limit_cny: Decimal

    def __post_init__(self):
        if not str(self.scope).strip() or not str(self.period).strip():
            raise ValueError('Envelope needs both a scope and a period')
        if Decimal(self.limit_cny) < 0:
            raise ValueError('Envelope limit must not be negative')


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    detail: str
    estimate_cny: Decimal
    reserved_cny: Decimal
    remaining_cny: Decimal
    lines: tuple = ()
    reservation_id: str = ''


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger(path: str | Path = DEFAULT_LEDGER) -> list[dict]:
    """Read the ledger. A malformed line raises rather than being skipped.

    Skipping would under-count spend, which is the one error this module exists to
    prevent; a corrupt ledger must stop the run, not quietly reduce the total.
    """
    ledger = Path(path)
    if not ledger.is_file():
        return []
    rows = []
    for number, line in enumerate(ledger.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f'ledger line {number} is not valid JSON: {error}') from None
    return rows


def append_ledger(rows, path: str | Path = DEFAULT_LEDGER) -> None:
    """Append rows with owner-only permissions. The file never exists unhardened."""
    ledger = Path(path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    payload = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows)
    if not payload:
        return
    handle = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(handle, 'a', encoding='utf-8') as stream:
        stream.write(payload)


def reserved(rows, envelope: Envelope) -> Decimal:
    """Spend already reserved against this envelope. Reservations count, not settlements."""
    total = Decimal('0')
    for row in rows:
        if row.get('kind') != 'reserve':
            continue
        if row.get('scope') != envelope.scope or row.get('period') != envelope.period:
            continue
        total += Decimal(str(row.get('estimated_cny', '0')))
    return total


def consumed(rows, envelope: Envelope) -> Decimal:
    """Budget that is gone or still held: settled actuals plus reservations still open.

    Settled reservations count at what they actually cost, so a call that failed and
    settled at zero returns its hold (rule 5). Unsettled ones still count at their
    estimate, which is what stops a second channel authorising against the same money
    (rule 2). :func:`reserved` answers a different question and is left alone: it sums
    estimates, so :func:`reconcile` can still compare them against the vendor.
    """
    scoped = [row for row in rows
              if row.get('scope') == envelope.scope and row.get('period') == envelope.period]
    actuals = {row.get('reservation_id'): Decimal(str(row.get('actual_cny', '0')))
               for row in scoped if row.get('kind') == 'settle'}
    reserved_ids = {row.get('reservation_id') for row in scoped if row.get('kind') == 'reserve'}
    total = Decimal('0')
    for row in scoped:
        if row.get('kind') == 'reserve':
            total += actuals.get(row.get('reservation_id'), Decimal(str(row.get('estimated_cny', '0'))))
        elif row.get('kind') == 'settle' and row.get('reservation_id') not in reserved_ids:
            # A settlement whose reservation is missing from the ledger is still money
            # out; counting it errs towards over-reporting rather than losing a charge.
            total += Decimal(str(row.get('actual_cny', '0')))
    return total


def remaining(rows, envelope: Envelope) -> Decimal:
    return Decimal(envelope.limit_cny) - consumed(rows, envelope)


def period_of(moment=None) -> str:
    """The period a call made at ``moment`` belongs to.

    The vendor counts its per-endpoint request quota on ``Asia/Shanghai`` days, so that
    is the boundary used here. Whether an envelope should *reset* on that boundary is
    still an open decision (METHODOLOGY §9.2); keeping the choice in one function is the
    point of having this at all.
    """
    stamp = moment or datetime.now(timezone.utc)
    stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m')


def envelope_from_env(scope, *, period: str = '', at=None) -> 'Envelope | None':
    """The envelope this machine may spend under, or ``None`` when none is declared.

    ``None`` is a decision, not a missing value: no envelope means no paid call, and a
    paid reader must fall back to a free one. A malformed amount is raised rather than
    treated as absent, because a typo in a spend ceiling should be loud, not degrade
    into "this deployment never spends" and get debugged as a source failure.
    """
    raw = os.environ.get(SPEND_LIMIT_ENV, '').strip()
    if not raw:
        return None
    try:
        limit = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f'{SPEND_LIMIT_ENV} must be a decimal CNY amount, got {raw!r}') from None
    return Envelope(str(scope), period or period_of(at), limit)


def ledger_from_env() -> Path:
    """Where spend rows go. Overridable so a test or a second machine can point elsewhere."""
    value = os.environ.get(SPEND_LEDGER_ENV, '').strip()
    return Path(value).expanduser() if value else DEFAULT_LEDGER


def estimate(calls, price_table: str | Path = pricing.DEFAULT_TABLE):
    """Total and per-endpoint lines for a call plan. Unknown endpoints raise."""
    lines, total = [], Decimal('0')
    for endpoint, count in calls.items():
        if count < 0:
            raise ValueError('call counts must not be negative')
        found = pricing.quote(endpoint, price_table)
        if not found.chargeable:
            raise ValueError(f'{endpoint} cannot be priced: permission='
                             f'{found.permission or "unknown"} price={found.unit_price}')
        cost = found.cost(count)
        total += cost
        lines.append({'endpoint': found.endpoint_path, 'calls': count,
                      'unit_price': str(found.unit_price), 'cost_cny': str(cost)})
    return total, tuple(lines)


def quote_recipe(recipe: str, price_table: str | Path = pricing.DEFAULT_TABLE) -> Decimal:
    """Worst-case JustOneAPI cost of one period of the named research mode."""
    if recipe not in RECIPE_CALLS:
        raise ValueError(f'unknown recipe {recipe!r}; expected one of {sorted(RECIPE_CALLS)}')
    return estimate(RECIPE_CALLS[recipe], price_table)[0]


def authorize(calls, envelope: Envelope, *, run_id: str = '', channel: str = 'mcp',
              scope_note: str = '', ledger: str | Path = DEFAULT_LEDGER) -> Decision:
    """Reserve budget for a call plan, or refuse it.

    Refusals are decisions, not exceptions raised from the pricing layer: the caller
    gets a reason code it can log and show, and ``BudgetDenied`` is only for callers
    that want the exception form.
    """
    if channel not in ('mcp', 'rest'):
        raise ValueError("channel must be 'mcp' or 'rest'")
    rows = load_ledger(ledger)
    available = remaining(rows, envelope)
    try:
        total, lines = estimate(calls)
    except (ValueError, FileNotFoundError) as error:
        return Decision(False, 'unpriced', str(error), Decimal('0'), reserved(rows, envelope),
                        available)
    if total > available:
        return Decision(False, 'insufficient_budget',
                        f'needs {total} but {available} remains in {envelope.scope}/{envelope.period}',
                        total, reserved(rows, envelope), available, lines)
    reservation_id = uuid.uuid4().hex[:12]
    append_ledger([{'kind': 'reserve', 'reservation_id': reservation_id, 'at': _now(),
                    'scope': envelope.scope, 'period': envelope.period, 'run_id': run_id,
                    'channel': channel, 'scope_note': scope_note,
                    'estimated_cny': str(total), 'lines': list(lines),
                    'price_table': Path(pricing.DEFAULT_TABLE).name,
                    'price_exported_at': pricing.EXPORTED_AT}], ledger)
    return Decision(True, 'authorized', 'reserved', total, reserved(rows, envelope) + total,
                    available - total, lines, reservation_id)


def require(calls, envelope: Envelope, **kwargs) -> Decision:
    """Same as :func:`authorize`, but raises ``BudgetDenied`` on refusal."""
    decision = authorize(calls, envelope, **kwargs)
    if not decision.allowed:
        raise BudgetDenied(decision)
    return decision


def settle(reservation_id: str, *, code=None, actual_cny=None, note: str = '',
           ledger: str | Path = DEFAULT_LEDGER) -> dict:
    """Record what a reservation actually cost, without altering its reserved amount.

    Pass ``code`` (the response's business code) whenever it is available: it is the only
    authoritative answer to "did this cost anything", and a failed call must settle at
    zero rather than at the reserved estimate. ``actual_cny`` stays available for the
    cases where reconciliation produces a number no single code can explain, e.g. a
    batch whose charges the vendor merged.

    Settlement never rewrites the reservation row (the ledger is append-only); it changes
    what the reservation *counts as* from here on, via :func:`consumed`.
    """
    if code is not None and actual_cny is not None:
        raise ValueError('pass either code or actual_cny, not both')
    rows = load_ledger(ledger)
    reservations = [r for r in rows if r.get('kind') == 'reserve'
                    and r.get('reservation_id') == reservation_id]
    if not reservations:
        raise ValueError(f'unknown reservation {reservation_id!r}')
    if any(r.get('kind') == 'settle' and r.get('reservation_id') == reservation_id for r in rows):
        raise ValueError(f'reservation {reservation_id!r} is already settled')
    expected = Decimal(str(reservations[0]['estimated_cny']))
    if code is not None:
        actual = expected if is_billed(code) else Decimal('0')
    else:
        actual = expected if actual_cny is None else Decimal(str(actual_cny))
    row = {'kind': 'settle', 'reservation_id': reservation_id, 'at': _now(),
           'scope': reservations[0]['scope'], 'period': reservations[0]['period'],
           'estimated_cny': str(expected), 'actual_cny': str(actual),
           'variance_cny': str(actual - expected), 'note': note,
           'billing_codes_version': BILLING_CODES_VERSION}
    if code is not None:
        row['code'] = code
        row['code_meaning'] = code_meaning(code)
        row['billed'] = is_billed(code)
    append_ledger([row], ledger)
    return row


def reconcile(observed_delta_cny, *, scope: str, period: str,
              ledger: str | Path = DEFAULT_LEDGER) -> dict:
    """Compare reserved estimates with an observed balance delta.

    Billing settles asynchronously and the MCP layer exposes no per-call detail, so the
    only ground truth is the balance difference. A persistent gap means the estimates are
    systematically wrong and the price table needs re-exporting.
    """
    rows = load_ledger(ledger)
    envelope = Envelope(scope, period, Decimal('0'))
    spend = reserved(rows, envelope)
    observed = Decimal(str(observed_delta_cny))
    return {'scope': scope, 'period': period, 'reserved_cny': str(spend),
            'observed_cny': str(observed), 'variance_cny': str(observed - spend),
            'reservations': sum(1 for r in rows if r.get('kind') == 'reserve'
                                and r.get('scope') == scope and r.get('period') == period)}


def report(scope: str, period: str, limit_cny, ledger: str | Path = DEFAULT_LEDGER) -> dict:
    """Envelope state for an operations view.

    ``reserved_cny`` is what was estimated and ``consumed_cny`` is what is actually gone
    or held; they differ once a call settles at something other than its estimate. The
    number the gate uses is ``remaining_cny``, which is derived from ``consumed_cny``.
    """
    envelope = Envelope(scope, period, Decimal(str(limit_cny)))
    rows = load_ledger(ledger)
    spend, held = reserved(rows, envelope), consumed(rows, envelope)
    channels = {}
    for row in rows:
        if row.get('kind') != 'reserve' or row.get('scope') != scope or row.get('period') != period:
            continue
        channels[row.get('channel', 'unknown')] = channels.get(row.get('channel', 'unknown'), 0) + 1
    return {'scope': scope, 'period': period, 'limit_cny': str(envelope.limit_cny),
            'reserved_cny': str(spend), 'consumed_cny': str(held),
            'remaining_cny': str(envelope.limit_cny - held),
            'reservations': sum(channels.values()), 'by_channel': channels,
            'price_table': Path(pricing.DEFAULT_TABLE).name,
            'price_exported_at': pricing.EXPORTED_AT}
