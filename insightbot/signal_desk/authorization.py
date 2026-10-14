"""Revocable local research grants. All permission events share the spend ledger lock.

No environment snapshot grants permission. Policies are explicitly set by a workspace
admin, approval signs immutable intent, and every new reservation checks live policy.
Network calls never hold the ledger lock. A reservation issued before revocation can
still finish and settle; revocation is not request cancellation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

from . import costcontrol as c

VERSION = 'authorization-1'
TZ = ZoneInfo('Asia/Shanghai')
INTENT_KEYS = ('brand_id', 'task_id', 'method_version', 'question', 'approach', 'task_type',
               'mode', 'mode_layers', 'structure', 'budget', 'source_config', 'queries',
               'keyword', 'start_date', 'end_date', 'audience', 'hypothesis', 'exclusions',
               'delivery_profile', 'brand_snapshot')


class AuthorizationError(PermissionError):
    pass


def stamp(at=None):
    value = at or datetime.now(timezone.utc)
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(TZ)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def intent(plan):
    return {key: copy.deepcopy(plan.get(key)) for key in INTENT_KEYS}


def _amount(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('额度必须是非负有限金额') from None
    if not result.is_finite() or result < 0:
        raise ValueError('额度必须是非负有限金额')
    return result


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('续期截止日期必须是 YYYY-MM-DD') from None


def _header(rows):
    headers = [row for row in rows if row.get('kind') == 'authorization_ledger']
    if len(headers) != 1:
        raise AuthorizationError('授权账本身份缺失或不一致；需管理员核对')
    if headers[0].get('schema_version') != VERSION or not headers[0].get('ledger_id'):
        raise AuthorizationError('授权账本版本无法核对')
    return headers[0]['ledger_id']


def _policy(rows, brand_id):
    return next((row for row in reversed(rows)
                 if row.get('kind') == 'authorization_policy' and row.get('scope') == brand_id), None)


def policy(path, brand_id):
    rows = c.load_ledger(path)
    found = _policy(rows, brand_id)
    if found:
        _header(rows)
    return found


def set_policy(path, brand_id, *, monthly_limit, enabled, allow_renew, renew_until,
               expected_version, actor, at=None):
    limit = _amount(monthly_limit)
    if not isinstance(enabled, bool) or not isinstance(allow_renew, bool):
        raise ValueError('额度启用与续期许可必须明确选择')
    if allow_renew and _date(renew_until) < stamp(at).date():
        raise ValueError('管理员续期截止日期已经过去')
    with c._ledger_lock(path) as locked:
        rows = c._read_ledger(locked)
        current = _policy(rows, brand_id)
        if expected_version != (current['version'] if current else 0):
            raise AuthorizationError('额度规则已变化，请刷新后保存')
        additions = []
        ledger_id = _header(rows) if any(r.get('kind') == 'authorization_ledger' for r in rows) else uuid.uuid4().hex
        if not any(r.get('kind') == 'authorization_ledger' for r in rows):
            additions.append({'kind': 'authorization_ledger', 'schema_version': VERSION, 'ledger_id': ledger_id, 'at': stamp(at).isoformat()})
        value = {'kind': 'authorization_policy', 'schema_version': VERSION, 'scope': brand_id,
                 'version': (current['version'] if current else 0) + 1,
                 'monthly_limit': str(limit), 'enabled': enabled, 'allow_renew': allow_renew,
                 'renew_until': renew_until if allow_renew else None, 'actor': actor,
                 'at': stamp(at).isoformat(), 'ledger_id': ledger_id}
        additions.append(value)
        if not enabled:
            additions.extend({'kind': 'authorization_revoke', 'schema_version': VERSION, 'grant_id': row['grant_id'],
                              'scope': brand_id, 'actor': actor, 'at': stamp(at).isoformat()}
                             for row in rows if row.get('kind') == 'authorization_grant'
                             and row.get('scope') == brand_id)
        c._append_ledger(additions, locked)
        return value


def call_limits(plan):
    budget = plan.get('budget', {})
    return {c.DETAIL_V1: int(budget.get('body_reads', 0)),
            c.COMMENT_V2: int(budget.get('comment_reads', 0))}


def terms(config, renew, until):
    if not isinstance(renew, bool):
        raise ValueError('必须明确选择是否跨月续期')
    if renew:
        _date(until)
        if not config:
            raise ValueError('只有明确启用的定时任务可以跨月续期')
    return {'schedule': copy.deepcopy(config), 'auto_renew': renew,
            'renew_until': until if renew else None}


def _preview(rows, plan, rule, term, at):
    _header(rows)
    if not rule or not rule['enabled']:
        raise AuthorizationError('本品牌未启用付费额度；请联系品牌管理员')
    if term['auto_renew']:
        until = _date(term['renew_until'])
        if until < stamp(at).date() or not rule['allow_renew'] or until > _date(rule['renew_until']):
            raise AuthorizationError('续期范围超出管理员许可或已经到期')
    maximum = c.estimate(call_limits(plan))[0]
    if maximum <= 0:
        raise AuthorizationError('本方案没有付费读取额度，请选择不付费执行')
    period = c.period_of(stamp(at))
    envelope = c.Envelope(plan['brand_id'], period, Decimal(rule['monthly_limit']))
    left = c.remaining(rows, envelope)
    # Balance is a live observation, not part of what the user approves. Confirmation
    # rereads it and denies insufficient funds without issuing a grant.
    value = {'version': VERSION, 'policy_version': rule['version'], 'period': period,
             'monthly_limit': rule['monthly_limit'], 'maximum_cny': str(maximum),
             'terms': term, 'intent_hash': digest(intent(plan)), 'ledger_id': _header(rows)}
    value['approval_token'] = digest(value)
    return value | {'remaining_cny': str(left), 'affordable': maximum <= left}


def preview(path, plan, *, schedule=None, auto_renew=False, renew_until=None, at=None):
    term = terms(schedule, auto_renew, renew_until)
    with c._ledger_lock(path, shared=True) as locked:
        rows = c._read_ledger(locked)
        return _preview(rows, plan, _policy(rows, plan['brand_id']), term, at)


def issue(path, plan, *, actor, confirmation_id, approval_token, schedule=None,
          auto_renew=False, renew_until=None, permission_check=None, at=None):
    term = terms(schedule, auto_renew, renew_until)
    grant_id = digest({'actor': actor, 'confirmation_id': confirmation_id, 'scope': plan['brand_id']})
    with c._ledger_lock(path) as locked:
        rows = c._read_ledger(locked)
        if permission_check:
            permission_check(actor)
        rule = _policy(rows, plan['brand_id'])
        current = _preview(rows, plan, rule, term, at)
        existing = next((r for r in rows if r.get('kind') == 'authorization_grant' and r['grant_id'] == grant_id), None)
        if existing:
            if existing['approval_token'] != approval_token or existing['intent'] != intent(plan) or existing['terms'] != term:
                raise AuthorizationError('同一确认编号不能用于不同授权')
            ref = _reference(existing, locked)
            _check(rows, ref, plan, at, permission_check)
            return ref
        if current['approval_token'] != approval_token:
            raise AuthorizationError('额度规则、月份或方案已变化，请刷新批准预览')
        if not current['affordable']:
            raise AuthorizationError('当前余量不足以容纳本轮付费需求，请调整后重新确认')
        grant = {'kind': 'authorization_grant', 'schema_version': VERSION, 'grant_id': grant_id, 'scope': plan['brand_id'],
                 'approved_by': actor, 'confirmation_id': confirmation_id,
                 'at': stamp(at).isoformat(), 'period': current['period'],
                 'monthly_limit': current['monthly_limit'], 'maximum_cny': current['maximum_cny'],
                 'policy_version': current['policy_version'], 'ledger_id': current['ledger_id'],
                 'plan_id': plan.get('id'),
                 'approval_token': approval_token, 'terms': term, 'intent': intent(plan),
                 'calls': call_limits(plan)}
        c._append_ledger([grant], locked)
        return _reference(grant, locked)


def _reference(grant, path):
    return {'version': VERSION, 'paid': True, 'grant_id': grant['grant_id'],
            'ledger_id': grant['ledger_id'], 'ledger_path': str(path),
            'approved_by': grant['approved_by'], 'period': grant['period'],
            'monthly_limit': grant['monthly_limit'], 'maximum_cny': grant['maximum_cny'],
            'terms': copy.deepcopy(grant['terms'])}


def free(plan, actor):
    return {'version': VERSION, 'paid': False, 'approved_by': actor, 'intent_hash': digest(intent(plan))}


def _check(rows, reference, plan, at, permission_check=None):
    if not reference or not reference.get('paid') or reference.get('version') != VERSION:
        raise AuthorizationError('没有有效付费授权；旧计划需重新确认')
    if _header(rows) != reference.get('ledger_id'):
        raise AuthorizationError('授权账本已变化；禁止重置余额后继续调用')
    grant = next((r for r in rows if r.get('kind') == 'authorization_grant'
                  and r.get('grant_id') == reference.get('grant_id')), None)
    if not grant or grant['scope'] != plan['brand_id']:
        raise AuthorizationError('授权不存在或不属于当前品牌')
    if permission_check:
        permission_check(grant['approved_by'])
    if any(r.get('kind') == 'authorization_revoke' and r.get('grant_id') == grant['grant_id'] for r in rows):
        raise AuthorizationError('付费授权已撤销；请重新确认，不会自动恢复')
    rule = _policy(rows, grant['scope'])
    if not rule or not rule['enabled']:
        raise AuthorizationError('品牌付费额度已停用')
    expected = copy.deepcopy(grant['intent'])
    config = grant['terms']['schedule']
    if config and plan.get('scheduled_for'):
        from . import scheduling_v2
        expected = scheduling_v2.frozen_run(expected, config['window'], datetime.fromisoformat(plan['scheduled_for']))
    if intent(plan) != expected:
        raise AuthorizationError('方案范围已变化；请重新确认付费授权')
    if stamp(at) < datetime.fromisoformat(grant['at']):
        raise AuthorizationError('当前时钟早于批准时间；需核对后继续')
    current_period = c.period_of(stamp(at))
    if current_period != grant['period']:
        term = grant['terms']
        if not term['auto_renew'] or not rule['allow_renew']:
            raise AuthorizationError('月度付费授权已到期；自动执行需重新确认')
        if stamp(at).date() > min(_date(term['renew_until']), _date(rule['renew_until'])):
            raise AuthorizationError('跨月续期已超过截止日期')
    elif grant['terms']['auto_renew'] and stamp(at).date() > _date(grant['terms']['renew_until']):
        raise AuthorizationError('付费授权已超过截止日期')
    return grant, rule, current_period


def check(path, reference, plan, *, at=None, permission_check=None):
    if str(Path(path).expanduser().resolve()) != reference.get('ledger_path'):
        raise AuthorizationError('账本路径与批准记录不一致')
    with c._ledger_lock(path, shared=True) as locked:
        rows = c._read_ledger(locked)
        grant, rule, period = _check(rows, reference, plan, at, permission_check)
        return c.Envelope(grant['scope'], period, min(Decimal(grant['monthly_limit']), Decimal(rule['monthly_limit'])))


def revoke(path, reference, *, actor, scope, at=None):
    with c._ledger_lock(path) as locked:
        rows = c._read_ledger(locked)
        if _header(rows) != reference.get('ledger_id'):
            raise AuthorizationError('授权账本身份不一致')
        grant = next((r for r in rows if r.get('kind') == 'authorization_grant'
                      and r.get('grant_id') == reference.get('grant_id') and r['scope'] == scope), None)
        if not grant:
            raise AuthorizationError('授权不存在或不属于当前品牌')
        if not any(r.get('kind') == 'authorization_revoke' and r.get('grant_id') == grant['grant_id'] for r in rows):
            c._append_ledger([{'kind': 'authorization_revoke', 'schema_version': VERSION, 'grant_id': grant['grant_id'],
                              'scope': scope, 'actor': actor, 'at': stamp(at).isoformat()}], locked)
        return grant['grant_id']


def reserve(path, reference, plan, calls, *, run_id, request_id, at=None, permission_check=None):
    """Revocation check, current month budget and reserve are one P0 transaction."""
    try:
        if str(Path(path).expanduser().resolve()) != reference.get('ledger_path'):
            raise AuthorizationError('账本路径与批准记录不一致')
        with c._ledger_lock(path) as locked:
            rows = c._read_ledger(locked)
            grant, rule, period = _check(rows, reference, plan, at, permission_check)
            if grant.get('plan_id'):
                if grant['terms']['schedule']:
                    from . import scheduling_v2
                    due = scheduling_v2.instant(plan.get('scheduled_for')) if plan.get('scheduled_for') else None
                    expected_run = ('schedule_' + digest({'confirmation': grant['grant_id'], 'due': due.isoformat()})[:40]) if due else None
                    if (not due or stamp(at) < due or run_id != expected_run or plan.get('id') != run_id
                            or plan.get('scheduled_from_plan_id') != grant['plan_id']):
                        raise AuthorizationError('定时付费调用未绑定本次获准触发')
                elif run_id != 'plan_' + grant['plan_id'] or plan.get('id') != grant['plan_id']:
                    raise AuthorizationError('付费调用未绑定已批准的研究运行')
            total, lines = c.estimate(calls)
            prior = [r for r in rows if r.get('kind') == 'reserve' and r.get('grant_id') == grant['grant_id']
                     and r.get('run_id') == run_id]
            if any(r.get('request_id') == request_id for r in prior):
                raise AuthorizationError('调用已经预留过；请核对结果，不会重复请求')
            for endpoint, count in calls.items():
                used = sum(line['calls'] for row in prior for line in row['lines'] if line['endpoint'] == endpoint)
                if not isinstance(count, int) or count < 1 or used + count > grant['calls'].get(endpoint, 0):
                    raise AuthorizationError('调用超出已批准的来源或次数')
            # Holds still count across month boundaries for this same research run.
            run_cost = sum(Decimal(r['estimated_cny']) for r in prior)
            if run_cost + total > Decimal(grant['maximum_cny']):
                raise AuthorizationError('本轮付费上限已用尽')
            envelope = c.Envelope(grant['scope'], period, min(Decimal(grant['monthly_limit']), Decimal(rule['monthly_limit'])))
            available = c.remaining(rows, envelope)
            if total > available:
                raise AuthorizationError('品牌本月付费额度不足')
            additions = []
            if period != grant['period'] and not any(r.get('kind') == 'authorization_period'
                    and r.get('grant_id') == grant['grant_id'] and r.get('period') == period for r in rows):
                additions.append({'kind': 'authorization_period', 'schema_version': VERSION, 'grant_id': grant['grant_id'],
                                  'scope': grant['scope'], 'period': period,
                                  'policy_version': rule['version'], 'at': stamp(at).isoformat()})
            reservation_id = uuid.uuid4().hex
            additions.append({'kind': 'reserve', 'reservation_id': reservation_id,
                'scope': grant['scope'], 'period': period, 'run_id': run_id, 'request_id': request_id,
                'grant_id': grant['grant_id'], 'mode': plan['mode'], 'channel': 'rest',
                'estimated_cny': str(total), 'lines': list(lines), 'at': stamp(at).isoformat()})
            c._append_ledger(additions, locked)
            return c.Decision(True, 'authorized', 'reserved', total, c.reserved(rows, envelope) + total,
                              available - total, lines, reservation_id)
    except (PermissionError, ValueError) as error:
        raise c.BudgetDenied(c.Decision(False, 'authorization_denied', str(error), Decimal('0'),
                                       Decimal('0'), Decimal('0'))) from None
