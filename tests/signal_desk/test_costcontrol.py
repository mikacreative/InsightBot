"""Price quoting and the spend ledger, against the real 2026-10-11 price export."""
from decimal import Decimal
from pathlib import Path

import pytest

# No importorskip here on purpose: pricing and costcontrol import nothing heavy, so the
# spend gate stays testable even where the isolated Signal Desk runtime is absent.
from insightbot.signal_desk import costcontrol as c, pricing


# --- pricing: the two endpoint spellings must join, and unknown must stay unknown --------

def test_rest_path_and_mcp_id_resolve_to_the_same_quote():
    by_path = pricing.quote('/api/xiaohongshu/search-note/v4')
    by_id = pricing.quote('xiaohongshu.search_note_v4')
    assert by_path.key == by_id.key == 'xiaohongshu_search_note_v4'
    assert by_path.unit_price == by_id.unit_price == Decimal('0.2000')


def test_measured_unit_prices_match_the_vendor_export():
    # The 2026-10-11 balance-difference measurements are corroborated by the export:
    # v2 search ¥0.15, v4 search ¥0.20, and detail is ¥0.15 rather than the
    # "<=¥0.10, no charge observed" the balance trail had suggested.
    assert pricing.price_of('/api/xiaohongshu/search-note/v2') == Decimal('0.1500')
    assert pricing.price_of('/api/xiaohongshu/search-note/v4') == Decimal('0.2000')
    assert pricing.price_of('/api/xiaohongshu/get-note-detail/v1') == Decimal('0.1500')
    assert pricing.price_of('/api/xiaohongshu/get-note-comment/v2') == Decimal('0.1500')


def test_unknown_and_unavailable_endpoints_are_not_free():
    unknown = pricing.quote('/api/xiaohongshu/not-a-real-endpoint/v9')
    assert unknown.known is False and unknown.chargeable is False
    assert pricing.price_of('/api/xiaohongshu/not-a-real-endpoint/v9') is None
    with pytest.raises(ValueError):
        unknown.cost(3)
    # 未开通 endpoints are in the table with no price: still refused, never billed as zero.
    unavailable = [q for q in pricing.price_table().values() if q.permission == 'unavailable']
    assert unavailable and all(not q.chargeable for q in unavailable)


def test_cheapest_alternate_version_wins():
    assert pricing.cheapest([c.SEARCH_V4, '/api/xiaohongshu/search-note/v2']).unit_price == Decimal('0.1500')


def test_price_table_has_no_key_collisions_and_matches_the_export_totals():
    summary = pricing.table_summary()
    assert summary['endpoints'] == 296 and summary['platforms'] == 35
    assert summary['unpriced'] == 2
    assert sum(summary['by_price'].values()) == 294


# --- costcontrol: deny by default, reserve before spending -------------------------------

def envelope(limit='5', scope='fictional-brand', period='2026-10'):
    return c.Envelope(scope, period, Decimal(limit))


def test_recipe_worst_case_costs_are_within_a_normal_month_envelope(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    e = envelope('5')
    # scan 2x0.20+1x0.15; probe 2x0.20+3x0.15; frame 3x0.20+6x0.15. Scan's recipe was
    # reconciled with METHODOLOGY §4 when modes moved into the execution layer: §3 makes a
    # challenge query mandatory and §4 says a scan reports 在用的词, which §2.2 forbids reading
    # off a truncated summary — so a search-only scan could not produce what it claimed.
    for recipe, expected in (('scan', '0.5500'), ('probe', '0.8500'), ('frame', '1.5000')):
        assert c.quote_recipe(recipe) == Decimal(expected)
        decision = c.authorize(c.RECIPE_CALLS[recipe], e, run_id=recipe, ledger=ledger)
        assert decision.allowed and decision.estimate_cny == Decimal(expected)
        c.settle(decision.reservation_id, ledger=ledger)


def test_reservation_covers_all_three_modes_then_refuses_the_next(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    e = envelope('3')
    spent = Decimal('0')
    for recipe in ('scan', 'probe', 'frame'):
        decision = c.authorize(c.RECIPE_CALLS[recipe], e, ledger=ledger)
        assert decision.allowed
        spent += decision.estimate_cny
    assert spent == Decimal('2.9000') and c.remaining(c.load_ledger(ledger), e) == Decimal('0.1000')
    refused = c.authorize(c.RECIPE_CALLS['scan'], e, ledger=ledger)
    assert not refused.allowed and refused.reason == 'insufficient_budget'
    with pytest.raises(c.BudgetDenied):
        c.require(c.RECIPE_CALLS['scan'], e, ledger=ledger)


def test_unpriced_plan_is_refused_rather_than_estimated(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    decision = c.authorize({'xiaohongshu.made_up_v9': 1}, envelope('5'), ledger=ledger)
    assert not decision.allowed and decision.reason == 'unpriced'
    assert c.load_ledger(ledger) == []


def test_two_channels_share_one_ledger_and_cannot_double_spend(tmp_path):
    """The MCP path and the REST path are separate processes but one budget."""
    ledger = tmp_path / 'spend.jsonl'
    e = envelope('0.9')
    first = c.authorize({c.SEARCH_V4: 2, c.DETAIL_V1: 3}, e,
                        channel='mcp', run_id='agent', ledger=ledger)
    assert first.allowed and first.estimate_cny == Decimal('0.8500')
    second = c.authorize({c.SEARCH_V4: 1}, e, channel='rest', run_id='provider', ledger=ledger)
    assert not second.allowed and second.reason == 'insufficient_budget'
    assert second.detail.endswith('0.0500 remains in fictional-brand/2026-10')


def test_envelope_periods_and_scopes_do_not_leak_into_each_other(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    c.authorize(c.RECIPE_CALLS['probe'], envelope('5', scope='brand-a', period='2026-10'), ledger=ledger)
    other = c.Envelope('brand-a', '2026-11', Decimal('5'))
    assert c.remaining(c.load_ledger(ledger), other) == Decimal('5')
    assert c.remaining(c.load_ledger(ledger), c.Envelope('brand-b', '2026-10', Decimal('5'))) == Decimal('5')


def test_settling_above_the_estimate_raises_the_hold_without_rewriting_the_row(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    decision = c.authorize(c.RECIPE_CALLS['probe'], envelope('5'), ledger=ledger)
    row = c.settle(decision.reservation_id, actual_cny='1.0000', note='detail also billed', ledger=ledger)
    assert row['variance_cny'] == '0.1500'
    # The reservation row itself is never edited — the ledger is append-only — but what
    # it counts as moves from the estimate to the actual, so the hold grows by ¥0.15.
    assert c.remaining(c.load_ledger(ledger), envelope('5')) == Decimal('4.0000')
    assert c.reserved(c.load_ledger(ledger), envelope('5')) == Decimal('0.8500')
    with pytest.raises(ValueError, match='already settled'):
        c.settle(decision.reservation_id, ledger=ledger)
    with pytest.raises(ValueError, match='unknown reservation'):
        c.settle('nope', ledger=ledger)


def test_corrupt_ledger_stops_the_run_instead_of_undercounting(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    ledger.write_text('{"kind": "reserve", "estimated_cny": "0.2"}\nnot json\n', encoding='utf-8')
    with pytest.raises(ValueError, match='line 2'):
        c.load_ledger(ledger)


# --- billing codes: the vendor bills code=0 only, so settle must not guess -----------------

def test_only_code_zero_is_billed():
    assert c.is_billed(0) is True
    for code in (100, 301, 302, 303, 400, 500, 600, 601, 602):
        assert c.is_billed(code) is False, code
        assert c.code_meaning(code) != f'未知业务码 {code}'


def test_unknown_billing_code_is_assumed_charged():
    # Fail-closed in the opposite direction from pricing: an unknown *price* is refused
    # because spending blind is the risk, but an unknown *code* counts as charged because
    # under-counting spend is the risk. Both mistakes must point away from losing money.
    assert c.is_billed(999) is True
    assert c.is_billed('weird') is True
    assert c.code_meaning(999) == '未知业务码 999'


def test_failed_call_settles_at_zero_and_gives_the_budget_back(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    decision = c.authorize(c.RECIPE_CALLS['scan'], envelope('5'), ledger=ledger)
    row = c.settle(decision.reservation_id, code=301, note='采集失败', ledger=ledger)
    assert row['actual_cny'] == '0'
    assert row['variance_cny'] == '-0.5500'
    assert row['billed'] is False and row['code_meaning'] == '采集失败，请重试'
    assert row['billing_codes_version'] == c.BILLING_CODES_VERSION
    # Held while in flight, released once it settles: a month of failed calls must not
    # close an envelope that never spent anything.
    assert c.consumed(c.load_ledger(ledger), envelope('5')) == Decimal('0')
    assert c.remaining(c.load_ledger(ledger), envelope('5')) == Decimal('5')


def test_an_open_reservation_still_blocks_the_other_channel(tmp_path):
    """Releasing on settlement must not release anything that is still in flight."""
    ledger = tmp_path / 'spend.jsonl'
    decision = c.authorize(c.RECIPE_CALLS['scan'], envelope('0.55'), ledger=ledger)
    assert decision.allowed and c.remaining(c.load_ledger(ledger), envelope('0.55')) == Decimal('0')
    settled = c.settle(decision.reservation_id, code=0, ledger=ledger)
    assert settled['actual_cny'] == '0.5500'
    assert c.remaining(c.load_ledger(ledger), envelope('0.55')) == Decimal('0')


def test_successful_call_settles_at_the_estimate(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    decision = c.authorize(c.RECIPE_CALLS['probe'], envelope('5'), ledger=ledger)
    row = c.settle(decision.reservation_id, code=0, ledger=ledger)
    assert row['actual_cny'] == row['estimated_cny'] == '0.8500'
    assert row['variance_cny'] == '0.0000'


def test_settle_refuses_an_ambiguous_code_and_amount(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    decision = c.authorize(c.RECIPE_CALLS['scan'], envelope('5'), ledger=ledger)
    with pytest.raises(ValueError, match='not both'):
        c.settle(decision.reservation_id, code=0, actual_cny='0.2', ledger=ledger)


def test_reconcile_and_report_expose_the_estimate_gap(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    c.authorize(c.RECIPE_CALLS['probe'], envelope('5'), channel='mcp', mode='probe', ledger=ledger)
    c.authorize(c.RECIPE_CALLS['scan'], envelope('5'), channel='rest', mode='scan', ledger=ledger)
    state = c.report('fictional-brand', '2026-10', '5', ledger=ledger)
    assert state['reserved_cny'] == '1.4000' and state['remaining_cny'] == '3.6000'
    # Nothing has settled yet, so what is held is what was estimated.
    assert state['consumed_cny'] == '1.4000'
    assert state['by_channel'] == {'mcp': 1, 'rest': 1}
    # One envelope carries every mode in the period, so spend has to be separable by mode:
    # otherwise a Frame's real cost cannot be compared with the recipe that was quoted for it.
    assert state['by_mode'] == {'probe': 1, 'scan': 1}
    assert state['spent_by_mode'] == {'probe': '0.8500', 'scan': '0.5500'}
    assert c.report('fictional-brand', '2026-10', '5', mode='scan', ledger=ledger)['consumed_cny'] == '0.5500'
    assert state['price_exported_at'] == pricing.EXPORTED_AT
    gap = c.reconcile('1.5500', scope='fictional-brand', period='2026-10', ledger=ledger)
    assert gap['variance_cny'] == '0.1500' and gap['reservations'] == 2


# --- the gate's own configuration: no declared limit means no paid call -----------------

def test_no_declared_limit_means_no_spending(monkeypatch):
    monkeypatch.delenv(c.SPEND_LIMIT_ENV, raising=False)
    assert c.envelope_from_env('fictional-brand') is None
    monkeypatch.setenv(c.SPEND_LIMIT_ENV, '   ')
    assert c.envelope_from_env('fictional-brand') is None


def test_declared_limit_becomes_an_envelope_for_the_named_scope(monkeypatch):
    monkeypatch.setenv(c.SPEND_LIMIT_ENV, '2.60')
    e = c.envelope_from_env('fictional-brand', period='2026-10')
    assert (e.scope, e.period, e.limit_cny) == ('fictional-brand', '2026-10', Decimal('2.60'))
    # A typo in a ceiling is loud, not silently "this deployment never spends".
    monkeypatch.setenv(c.SPEND_LIMIT_ENV, 'about two yuan')
    with pytest.raises(ValueError, match=c.SPEND_LIMIT_ENV):
        c.envelope_from_env('fictional-brand')


def test_period_follows_the_vendor_day_boundary():
    # 2026-10-31T17:00Z is 2026-11-01 in Asia/Shanghai, which is where the vendor counts.
    from datetime import datetime, timezone
    stamp = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
    assert c.period_of(stamp) == '2026-11'
    assert c.period_of(datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)) == '2026-10'


def test_ledger_location_is_overridable(monkeypatch, tmp_path):
    monkeypatch.delenv(c.SPEND_LEDGER_ENV, raising=False)
    assert c.ledger_from_env() == c.DEFAULT_LEDGER
    monkeypatch.setenv(c.SPEND_LEDGER_ENV, str(tmp_path / 'spend.jsonl'))
    assert c.ledger_from_env() == tmp_path / 'spend.jsonl'


def test_ledger_file_is_created_owner_only(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    c.authorize(c.RECIPE_CALLS['scan'], envelope('5'), ledger=ledger)
    assert oct(ledger.stat().st_mode)[-3:] == '600'


def test_channel_and_envelope_inputs_are_validated(tmp_path):
    ledger = tmp_path / 'spend.jsonl'
    with pytest.raises(ValueError, match='channel'):
        c.authorize(c.RECIPE_CALLS['scan'], envelope('5'), channel='telepathy', ledger=ledger)
    with pytest.raises(ValueError, match='scope and a period'):
        c.Envelope('', '2026-10', Decimal('5'))
    with pytest.raises(ValueError, match='must not be negative'):
        c.Envelope('brand', '2026-10', Decimal('-1'))
    with pytest.raises(ValueError, match='unknown recipe'):
        c.quote_recipe('deep-dive')
    with pytest.raises(ValueError, match='not be negative'):
        c.estimate({c.SEARCH_V4: -1})


def test_default_ledger_is_gitignored():
    """Spend rows carry brand scope and run ids; data/*.jsonl is the ignore rule."""
    ignore = (Path(__file__).resolve().parents[2] / '.gitignore').read_text(encoding='utf-8')
    assert 'data/*.jsonl' in ignore
    assert c.DEFAULT_LEDGER.parent.name == 'data'
