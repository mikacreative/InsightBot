"""Isolated, brand-authorized v0.2 workspace. Existing v0.1 data is never migrated.

The HTTP adapter authenticates sessions and CSRF. This module independently checks
brand membership for every resource, including guessed IDs and exported artifacts.
Only an explicitly confirmed immutable plan can enqueue provider work; recovery
never repeats an uncertain request. LangGraph checkpoints live in each brand's new
v2 directory, separate from all legacy databases.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


from .research_v2 import DELIVERY_DEFAULTS
from . import scheduling_v2

DEFAULT_DELIVERY = copy.deepcopy(DELIVERY_DEFAULTS)
ROLES = {'admin', 'researcher', 'reviewer'}
KINDS = ('issues', 'tasks', 'plans', 'jobs', 'editions', 'feedback', 'revisions', 'planning',
         'schedules', 'schedule_proposals', 'schedule_runs', 'dialogue_events')
ACTIVE = {'queued', 'collecting', 'editing', 'enriching', 'reediting', 'validating', 'running'}
FEEDBACK = {'useful', 'known', 'unsupported', 'irrelevant', 'investigate',
            '有参考', '已知或重复', '依据不足', '无关', '值得补证'}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ValueError('记录编号无效')
    return value


def text_field(value, maximum=4000, required=False):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError('文字长度或格式无效')
    value = value.strip()
    if required and not value:
        raise ValueError('请补充必填内容')
    return value


def plan_reply(plan):
    if plan.get('questions'):
        return '\n'.join(plan['questions'])
    if plan.get('needs_revision'):
        return '研究方向已经整理好了。方案的搜索范围还需要调整，你可以在下方设置里修改。'
    return '方案已经整理好了。你可以开始研究，也可以继续告诉我想改哪一部分。'


def merge_turns(history, recent):
    """Keep the full dialogue separate from the bounded context sent to a model."""
    for overlap in range(min(len(history), len(recent)), -1, -1):
        if not overlap or history[-overlap:] == recent[:overlap]:
            return history + copy.deepcopy(recent[overlap:])


class ResearchState(TypedDict, total=False):
    brand_id: str
    task_id: str
    run_id: str
    plan: dict
    collected: dict
    delivery: dict
    errors: list
    review: dict
    status: str


class ScheduledPauseError(RuntimeError):
    """Code-owned explanation; never interpolate a provider exception."""


class WorkspaceV2:
    def __init__(self, root, start_worker=True, schedule_clock=None):
        self.root = Path(root).resolve()
        self.base = self.root / 'v2'
        self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        self._schedule_clock = schedule_clock or (lambda: datetime.now(timezone.utc))
        self._scheduler_cursor = scheduling_v2.instant(self._schedule_clock())
        self._scheduler_stop = threading.Event()
        # Mark uncertainty explicitly; do not rerun providers on service startup.
        for directory in self.base.iterdir():
            if not directory.is_dir() or not (directory / 'brand.json').exists():
                continue
            for operation in self._list(directory.name, 'planning'):
                if operation.get('status') == 'running':
                    operation.update(status='interrupted', updated_at=now())
                    self._save(directory.name, 'planning', operation)
            for job in self._list(directory.name, 'jobs'):
                if job.get('status') in ACTIVE:
                    job.update(status='interrupted', updated_at=now(),
                               error='服务曾中断，可能已有数据或模型调用；不会自动重试。')
                    self._save(directory.name, 'jobs', job)
                    if job.get('schedule_id'):
                        self._finish_scheduled_job(directory.name, job)
            for schedule in self._list(directory.name, 'schedules'):
                if not schedule.get('enabled'):
                    continue
                reason = self._schedule_guard(directory.name, schedule)
                uncertain = next((run for run in self._list(directory.name, 'schedule_runs')
                    if run.get('confirmation_id') == schedule.get('confirmation_id')
                    and run.get('status') in ('claimed', 'queued')
                    and not (self._directory(directory.name) / 'jobs' / (run['id'] + '.json')).is_file()), None)
                orphan = False
                for marker in (directory / 'schedule-trigger-started').glob('*.started'):
                    if (directory / 'schedule_runs' / (marker.stem + '.json')).is_file():
                        continue
                    try:
                        claim = json.loads(marker.read_text(encoding='utf-8'))
                        orphan = claim.get('confirmation_id') == schedule.get('confirmation_id')
                    except (OSError, ValueError, AttributeError):
                        orphan = True
                    if orphan:
                        break
                if reason or uncertain or orphan:
                    self._pause_schedule(directory.name, schedule['id'], reason or
                        '触发曾中断，执行结果需要核对；自动执行已暂停，不会重试。')
                    continue
                future = scheduling_v2.next_occurrence(self._schedule_config(schedule), self._scheduler_cursor)
                if future is None:
                    self._pause_schedule(directory.name, schedule['id'],
                        '服务未运行时已错过一次执行；请重新设置未来时间。')
                else:
                    schedule.update(next_run_at=future, updated_at=now())
                    self._save(directory.name, 'schedules', schedule)
        if start_worker:
            self.worker = threading.Thread(target=self._worker, daemon=True,
                                           name='signal-desk-v2')
            self.worker.start()
            self.scheduler = threading.Thread(target=self._scheduler, daemon=True,
                                               name='signal-desk-v2-scheduler')
            self.scheduler.start()

    def _directory(self, brand_id):
        return self.base / identifier(brand_id)

    @staticmethod
    def _write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return copy.deepcopy(value)

    def _save(self, brand_id, kind, value):
        if kind not in KINDS or value.get('brand_id') != brand_id:
            raise ValueError('记录品牌不匹配')
        return self._write(self._directory(brand_id) / kind /
                           (identifier(value['id']) + '.json'), value)

    def _read(self, brand_id, kind, key):
        if kind not in KINDS:
            raise ValueError('记录类型无效')
        path = self._directory(brand_id) / kind / (identifier(key) + '.json')
        if not path.is_file():
            raise ValueError('记录不存在')
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('brand_id') != brand_id:
            raise ValueError('记录品牌不匹配')
        return value

    def _list(self, brand_id, kind):
        result = []
        for path in (self._directory(brand_id) / kind).glob('*.json'):
            value = self._read(brand_id, kind, path.stem)
            result.append(value)
        return sorted(result, key=lambda v: v.get('updated_at', v.get('created_at', '')),
                      reverse=True)

    def _brand(self, brand_id, user, permission='read'):
        username = user.get('username') if isinstance(user, dict) else None
        if not username:
            raise PermissionError('需要登录')
        path = self._directory(brand_id) / 'brand.json'
        if not path.is_file():
            raise PermissionError('无权访问该品牌或记录')
        brand = json.loads(path.read_text(encoding='utf-8'))
        roles = brand.get('members', {}).get(username, [])
        if isinstance(roles, str):
            roles = [roles]
        if user.get('role') == 'admin':
            roles = ['admin', 'researcher', 'reviewer']
        if not roles or (permission != 'read' and permission not in roles and 'admin' not in roles):
            raise PermissionError('无权访问该品牌或记录')
        return brand, roles

    def _public_brand(self, brand, roles):
        result = copy.deepcopy(brand)
        result['roles'] = roles
        result['role'] = 'admin' if 'admin' in roles else roles[0]
        if 'admin' not in roles:
            result.pop('members', None)
        return result

    def brands(self, user):
        result = []
        with self.lock:
            for directory in self.base.iterdir():
                if not directory.is_dir() or not (directory / 'brand.json').exists():
                    continue
                try:
                    brand, roles = self._brand(directory.name, user)
                except PermissionError:
                    continue
                # Homepage intentionally omits research, private briefs and member lists.
                result.append({k: brand.get(k, '') for k in ('id', 'name', 'updated_at')}
                              | {'roles': roles, 'role': 'admin' if 'admin' in roles else roles[0]})
        return {'brands': sorted(result, key=lambda b: b['name']), 'version': '0.2.1'}

    @staticmethod
    def _members(value):
        if not isinstance(value, dict) or len(value) > 100:
            raise ValueError('成员配置无效')
        result = {}
        for username, roles in value.items():
            if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', username):
                raise ValueError('成员账号无效')
            if isinstance(roles, str):
                roles = [roles]
            if not isinstance(roles, list) or not roles or not set(roles) <= ROLES:
                raise ValueError('成员角色无效')
            result[username.lower()] = sorted(set(roles))
        return result

    def save_brand(self, payload, user, create=False):
        with self.lock:
            if create:
                if user.get('role') != 'admin':
                    raise PermissionError('仅管理员可新建品牌')
                brand_id = uuid.uuid4().hex
                brand = {'id': brand_id, 'brand_id': brand_id, 'created_at': now(),
                         'version': 0, 'members': {user['username']: ['admin', 'researcher', 'reviewer']},
                         'delivery_profile': copy.deepcopy(DEFAULT_DELIVERY), 'source_config': {},
                         'facts': []}
            else:
                brand_id = identifier(payload.get('brand_id'))
                brand, _ = self._brand(brand_id, user, 'admin')
            for field in ('name', 'description', 'audience', 'objective', 'region', 'language'):
                if field in payload:
                    brand[field] = text_field(payload[field], required=field == 'name')
            if not brand.get('name'):
                raise ValueError('请填写品牌名称')
            if 'members' in payload:
                brand['members'] = self._members(payload['members'])
                if not any('admin' in roles for roles in brand['members'].values()):
                    raise ValueError('品牌至少保留一位管理员')
            for field in ('source_config', 'facts'):
                if field in payload:
                    value = copy.deepcopy(payload[field])
                    if not isinstance(value, dict if field == 'source_config' else list):
                        raise ValueError('品牌资料格式无效')
                    if len(json.dumps(value, ensure_ascii=False)) > 30000:
                        raise ValueError('品牌资料过长')
                    # Provider secrets remain in server configuration, never brand JSON.
                    if re.search(r'"(?:api_key|token|password|secret|cookie)"\s*:',
                                 json.dumps(value), re.IGNORECASE):
                        raise ValueError('请在服务端配置凭证，不可写入品牌资料')
                    brand[field] = value
            if 'delivery_profile' in payload:
                # v0.2's contract is fixed during the first two reader trials.
                if payload['delivery_profile'] != DEFAULT_DELIVERY:
                    raise ValueError('本轮交付上限固定；调整需另行审核产品规格')
            brand.update(version=brand.get('version', 0) + 1, updated_at=now())
            self._write(self._directory(brand_id) / 'brand.json', brand)
            for kind in KINDS:
                (self._directory(brand_id) / kind).mkdir(exist_ok=True, mode=0o700)
            return self._public_brand(*self._brand(brand_id, user))

    def save_issue(self, payload, user):
        brand_id = identifier(payload.get('brand_id'))
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            if payload.get('id'):
                issue = self._read(brand_id, 'issues', payload['id'])
            else:
                issue = {'id': uuid.uuid4().hex, 'brand_id': brand_id,
                         'created_at': now(), 'created_by': user['username']}
            for field in ('title', 'question'):
                issue[field] = text_field(payload.get(field, issue.get(field, '')), required=True)
            issue['updated_at'] = now()
            return self._save(brand_id, 'issues', issue)

    @staticmethod
    def _schedule_config(record):
        return {key: record.get(key) for key in scheduling_v2.CONFIG_FIELDS}

    def _optional(self, brand_id, kind, key):
        path = self._directory(brand_id) / kind / (identifier(key) + '.json')
        return self._read(brand_id, kind, key) if path.is_file() else None

    @staticmethod
    def _public_schedule(schedule):
        if schedule is None:
            return None
        return {key: copy.deepcopy(value) for key, value in schedule.items()
                if key != 'plan_snapshot'}

    def _schedule_response(self, brand_id, task_id):
        return {'schedule': self._public_schedule(self._optional(brand_id, 'schedules', task_id)),
                'proposal': self._optional(brand_id, 'schedule_proposals', task_id)}

    def _current_account(self, username):
        """Read current account metadata, never retain or expose credential records."""
        try:
            users = json.loads((self.root / 'users.json').read_text(encoding='utf-8'))
            account = users.get(username) if isinstance(users, dict) else None
        except (OSError, ValueError):
            account = None
        if (not isinstance(account, dict) or account.get('role') not in ('admin', 'editor')
                or account.get('enabled') is False or account.get('active') is False
                or account.get('disabled') is True):
            raise PermissionError('启用账号已停用或无法核对；自动执行已暂停。')
        return {'username': username, 'role': account['role']}

    def _plan_revision_reason(self, brand_id, plan, task=None):
        task = task or self._read(brand_id, 'tasks', plan['task_id'])
        if task.get('latest_plan_id') != plan['id'] or plan.get('scheduled_from_plan_id'):
            return '研究方案已有新版本，请刷新并确认最新方案'
        operation = max((o for o in self._list(brand_id, 'planning')
                         if o.get('task_id') == task['id']),
                        key=lambda o: o.get('created_at', ''), default=None)
        if (operation and operation.get('status') in ('running', 'failed', 'interrupted')
                and operation.get('created_at', '') >= plan.get('created_at', '')):
            return ('正在修改研究方案，请等回复后确认最新方案' if operation['status'] == 'running'
                    else '上次研究方案修改未完成，请核对并重新生成方案后确认')
        return None

    def _schedule_guard(self, brand_id, schedule):
        try:
            user = self._current_account(schedule['created_by'])
            self._brand(brand_id, user, 'researcher')
        except PermissionError:
            return '启用账号或品牌研究权限已失效；自动执行已暂停。'
        try:
            task = self._read(brand_id, 'tasks', schedule['task_id'])
            plan = self._read(brand_id, 'plans', schedule['plan_id'])
        except ValueError:
            return '原研究方案已不可用；请重新确认自动执行。'
        revision_reason = self._plan_revision_reason(brand_id, plan, task)
        if revision_reason:
            return revision_reason + '；自动执行已暂停。'
        if plan.get('checksum') != schedule['plan_checksum'] or not plan.get('ready'):
            return '研究方案已有新版本；请确认新方案后重新启用自动执行。'
        return None

    def _pause_schedule(self, brand_id, task_id, reason):
        schedule = self._optional(brand_id, 'schedules', task_id)
        if schedule:
            schedule.update(enabled=False, status='paused', paused_reason=reason,
                            next_run_at=None, updated_at=now())
            self._save(brand_id, 'schedules', schedule)
        return schedule

    def _dialogue_event(self, brand_id, task_id, instruction, reply):
        event = {'id': uuid.uuid4().hex, 'brand_id': brand_id, 'task_id': task_id,
                 'kind': 'schedule', 'created_at': now(),
                 'turns': [{'role': 'user', 'content': instruction},
                           {'role': 'assistant', 'content': reply}]}
        self._save(brand_id, 'dialogue_events', event)
        return event

    def schedule_preview(self, payload, user):
        brand_id, task_id = identifier(payload.get('brand_id')), identifier(payload.get('task_id'))
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            self._read(brand_id, 'tasks', task_id)
            at = scheduling_v2.instant(self._schedule_clock())
            prior_proposal = self._optional(brand_id, 'schedule_proposals', task_id) or {}
            prior_schedule = self._optional(brand_id, 'schedules', task_id) or {}
            inherited_window = prior_proposal.get('window', prior_schedule.get('window', 'fixed'))
            instruction = payload.get('instruction')
            if instruction is not None:
                instruction = text_field(instruction, 1000, required=True)
            pause = instruction is not None and re.sub(r'\s+', '', instruction).rstrip('。.!！') in {
                '暂停自动执行', '取消定时', '停止自动', '停止自动执行', '暂停定时', '停用自动执行'}
            config, message = None, None
            if not pause:
                try:
                    config = (scheduling_v2.parse_instruction(instruction, at, inherited_window) if instruction is not None
                              else scheduling_v2.configuration({key: payload[key] for key in
                                   scheduling_v2.CONFIG_FIELDS if key in payload}))
                    if config is None:
                        message = '这条时间说明还不够明确。请在自动执行设置中选择日期、每天或每周的具体时间。'
                    elif scheduling_v2.next_occurrence(config, at) is None:
                        message = '这次执行时间已经过去，请选择未来的日期和时间。'
                        config = None
                except ValueError as exc:
                    message = str(exc)
            if pause:
                self._pause_schedule(brand_id, task_id, '已按你的要求暂停自动执行。')
                message = '自动执行已暂停。需要恢复时，请检查设置并点击启用。'
            elif config:
                self._pause_schedule(brand_id, task_id,
                    '自动执行时间已有新提议；请确认新设置后重新启用。')
                message = scheduling_v2.summary(config) + ' 当前是待确认设置，点击启用后才会自动执行。'
            proposal = {'id': task_id, 'task_id': task_id, 'brand_id': brand_id,
                        'valid': bool(config), 'action': 'pause' if pause else 'configure',
                        'window': inherited_window,
                        'timezone': scheduling_v2.TIMEZONE, 'message': message,
                        'summary': scheduling_v2.summary(config) if config else message,
                        'next_run_at': scheduling_v2.next_occurrence(config, at) if config else None,
                        'instruction': instruction, 'created_at': now(), 'created_by': user['username']}
            if config:
                proposal.update(config)
            proposal['checksum'] = digest(proposal)
            self._save(brand_id, 'schedule_proposals', proposal)
            self._dialogue_event(brand_id, task_id, instruction or
                ('设置自动执行：' + (scheduling_v2.summary(config) if config else '手动调整执行时间')), message)
            return self._schedule_response(brand_id, task_id)

    def save_schedule(self, payload, user):
        brand_id, task_id = identifier(payload.get('brand_id')), identifier(payload.get('task_id'))
        if not isinstance(payload.get('enabled'), bool):
            raise ValueError('自动执行启用开关格式无效')
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            task = self._read(brand_id, 'tasks', task_id)
            if not payload['enabled']:
                self._pause_schedule(brand_id, task_id, '已手动暂停自动执行。')
                message = '自动执行已暂停。需要恢复时，请检查设置并点击启用。'
                self._dialogue_event(brand_id, task_id, '在任务详情暂停自动执行', message)
                return self._schedule_response(brand_id, task_id) | {'message': message}
            # A current account check also defeats a still-live session after revocation.
            self._brand(brand_id, self._current_account(user['username']), 'researcher')
            plan = self._read(brand_id, 'plans', payload.get('plan_id'))
            if plan['task_id'] != task_id or plan.get('scheduled_from_plan_id'):
                raise ValueError('自动执行必须绑定本任务的研究方案')
            if payload.get('checksum') != plan['checksum'] or task.get('latest_plan_id') != plan['id']:
                raise ValueError('研究方案已变化，请刷新并重新确认自动执行')
            if not plan.get('ready'):
                raise ValueError('研究方案还需要调整，暂时不能启用自动执行')
            config = scheduling_v2.configuration({key: payload[key] for key in
                                                  scheduling_v2.CONFIG_FIELDS if key in payload})
            at = scheduling_v2.instant(self._schedule_clock())
            future = scheduling_v2.next_occurrence(config, at)
            if future is None:
                raise ValueError('执行时间已经过去，请设置未来时间')
            if payload.get('proposal_checksum') is not None:
                proposal = self._optional(brand_id, 'schedule_proposals', task_id)
                if (not proposal or not proposal.get('valid') or
                        proposal.get('checksum') != payload['proposal_checksum'] or
                        config != self._schedule_config(proposal)):
                    raise ValueError('自动执行候选已变化，请刷新设置后确认')
            schedule = {'id': task_id, 'task_id': task_id, 'brand_id': brand_id,
                        'confirmation_id': uuid.uuid4().hex, 'enabled': True, 'status': 'enabled',
                        'plan_id': plan['id'], 'plan_checksum': plan['checksum'],
                        'plan_snapshot': copy.deepcopy(plan), 'timezone': scheduling_v2.TIMEZONE,
                        'summary': scheduling_v2.summary(config), 'next_run_at': future,
                        'created_at': now(), 'updated_at': now(), 'created_by': user['username'],
                        'paused_reason': None, 'last_run_at': None, 'last_job_id': None, **config}
            reason = self._schedule_guard(brand_id, schedule)
            if reason:
                raise ValueError(reason)
            prior = self._optional(brand_id, 'schedules', task_id)
            if (prior and prior.get('enabled') and prior.get('plan_id') == plan['id']
                    and prior.get('plan_checksum') == plan['checksum'] and prior.get('created_by') == user['username']
                    and self._schedule_config(prior) == config):
                # Repeated button submits do not invalidate an already queued run.
                return self._schedule_response(brand_id, task_id) | {
                    'message': '自动执行已启用。' + prior['summary']}
            self._save(brand_id, 'schedules', schedule)
            message = '自动执行已启用。' + schedule['summary'] + '每轮沿用确认的研究方案与额度，交付仍需审核。'
            try:
                self._dialogue_event(brand_id, task_id, '在任务详情启用自动执行', message)
            except Exception:
                self._pause_schedule(brand_id, task_id, '启用确认记录未保存完整；请检查后重新启用。')
                raise
            return self._schedule_response(brand_id, task_id) | {'message': message}

    def task_title(self, payload, user):
        brand_id, task_id = identifier(payload.get('brand_id')), identifier(payload.get('task_id'))
        title = text_field(payload.get('title'), 150, required=True)
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            task = self._read(brand_id, 'tasks', task_id)
            task.update(title=title, updated_at=now())
            return self._save(brand_id, 'tasks', task)

    def _scheduler(self):
        # No first-run catch-up. Neither this thread nor the service is an OS timer.
        while not self._scheduler_stop.wait(30):
            try:
                self.tick_schedules()
            except Exception:
                # A filesystem failure must not kill the service or leak credentials.
                # Durable claims prevent replay; the next tick can only advance safely.
                continue

    def tick_schedules(self, at=None):
        """Explicit clock entry point for tests; missed ticks are never replayed."""
        with self.lock:
            at = scheduling_v2.instant(at if at is not None else self._schedule_clock())
            gap = (at - self._scheduler_cursor).total_seconds()
            self._scheduler_cursor = at
            triggered = []
            for directory in self.base.iterdir():
                if not directory.is_dir() or not (directory / 'brand.json').is_file():
                    continue
                brand_id = directory.name
                for schedule in self._list(brand_id, 'schedules'):
                    if not schedule.get('enabled'):
                        continue
                    reason = self._schedule_guard(brand_id, schedule)
                    if reason:
                        self._pause_schedule(brand_id, schedule['id'], reason)
                        continue
                    if not schedule.get('next_run_at'):
                        self._pause_schedule(brand_id, schedule['id'], '自动执行时间不可用，请重新确认设置。')
                        continue
                    due = scheduling_v2.instant(schedule['next_run_at'])
                    if due > at:
                        continue
                    config = self._schedule_config(schedule)
                    future = scheduling_v2.next_occurrence(config, at)
                    # A delayed tick or a sleep gap skips the stale trigger altogether.
                    if gap < 0 or gap > 60 or (at - due).total_seconds() > 60:
                        if future is None:
                            self._pause_schedule(brand_id, schedule['id'],
                                '已错过一次执行；请重新设置未来时间。')
                        else:
                            schedule.update(next_run_at=future, last_skip_reason='本机服务曾停止或休眠，已跳过错过的执行。', updated_at=now())
                            self._save(brand_id, 'schedules', schedule)
                        continue
                    run_id = 'schedule_' + digest({'confirmation': schedule['confirmation_id'], 'due': due.isoformat()})[:40]
                    marker = directory / 'schedule-trigger-started' / (run_id + '.started')
                    marker.parent.mkdir(exist_ok=True, mode=0o700)
                    try:
                        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    except FileExistsError:
                        existing = self._optional(brand_id, 'schedule_runs', run_id)
                        if not existing or existing.get('status') in ('claimed', 'queued'):
                            self._pause_schedule(brand_id, schedule['id'],
                                '触发结果需要核对；自动执行已暂停，不会重复提交。')
                            job = self._optional(brand_id, 'jobs', run_id)
                            if job and job['status'] == 'queued':
                                job.update(status='interrupted', updated_at=now(),
                                           error='触发提交曾中断；执行结果需要核对，不会自动重试。')
                                self._save(brand_id, 'jobs', job)
                                self._finish_scheduled_job(brand_id, job)
                        else:
                            schedule.update(next_run_at=future, updated_at=now())
                            if future is None:
                                schedule.update(enabled=False, status='exhausted')
                            self._save(brand_id, 'schedules', schedule)
                        continue
                    with os.fdopen(fd, 'w') as stream:
                        json.dump({'task_id': schedule['task_id'], 'confirmation_id': schedule['confirmation_id'],
                                   'scheduled_for': due.isoformat()}, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    run = {'id': run_id, 'brand_id': brand_id, 'task_id': schedule['task_id'],
                           'confirmation_id': schedule['confirmation_id'], 'scheduled_for': due.isoformat(),
                           'status': 'claimed', 'created_at': now(), 'updated_at': now()}
                    self._save(brand_id, 'schedule_runs', run)
                    overlap = any(job.get('task_id') == schedule['task_id'] and job.get('status') in ACTIVE
                                  for job in self._list(brand_id, 'jobs'))
                    if overlap:
                        run.update(status='skipped_overlap', updated_at=now())
                        self._save(brand_id, 'schedule_runs', run)
                        schedule.update(next_run_at=future, last_skip_reason='上一轮仍在执行，已跳过本次自动执行。', updated_at=now())
                        if future is None:
                            schedule.update(enabled=False, status='paused', paused_reason='上一轮仍在执行，请另设未来时间。')
                        self._save(brand_id, 'schedules', schedule)
                        continue
                    plan = scheduling_v2.frozen_run(schedule['plan_snapshot'], schedule['window'], due)
                    plan.update(id=run_id, scheduled_from_plan_id=schedule['plan_id'],
                                schedule_id=schedule['id'], scheduled_for=due.isoformat(),
                                status='confirmed', created_at=now(), updated_at=now())
                    plan.pop('job_id', None)
                    plan.pop('checksum', None)
                    plan['checksum'] = digest(plan)
                    self._save(brand_id, 'plans', plan)
                    task = self._read(brand_id, 'tasks', schedule['task_id'])
                    job = {'id': run_id, 'run_id': run_id, 'brand_id': brand_id,
                           'task_id': task['id'], 'issue_id': plan.get('issue_id'),
                           'plan_id': run_id, 'plan_checksum': plan['checksum'],
                           'schedule_plan_id': schedule['plan_id'], 'schedule_id': schedule['id'],
                           'schedule_confirmation_id': schedule['confirmation_id'], 'scheduled_for': due.isoformat(),
                           'title': task.get('title') or task['request'], 'status': 'queued',
                           'created_by': schedule['created_by'], 'created_at': now(), 'updated_at': now()}
                    # Both the trigger claim and job exist before a worker can call a provider.
                    self._save(brand_id, 'jobs', job)
                    run.update(status='queued', job_id=run_id, updated_at=now())
                    self._save(brand_id, 'schedule_runs', run)
                    schedule.update(next_run_at=future, last_run_at=due.isoformat(),
                                    last_job_id=run_id, updated_at=now())
                    if future is None:
                        schedule.update(enabled=False, status='exhausted')
                    self._save(brand_id, 'schedules', schedule)
                    self.queue.put((brand_id, run_id))
                    triggered.append(copy.deepcopy(job))
            return triggered

    def create_plan(self, payload, user):
        from . import research_v2
        brand_id = identifier(payload.get('brand_id'))
        if 'use_ai' in payload and not isinstance(payload['use_ai'], bool):
            raise ValueError('AI规划开关格式无效')
        request_id = identifier(payload.get('request_id') or uuid.uuid4().hex)
        request_checksum = digest(payload)
        with self.lock:
            brand, _ = self._brand(brand_id, user, 'researcher')
            existing = self._directory(brand_id) / 'planning' / (request_id + '.json')
            if existing.exists():
                prior = self._read(brand_id, 'planning', request_id)
                if prior['request_checksum'] != request_checksum:
                    raise ValueError('同一规划请求编号不能用于不同内容')
                if prior['status'] == 'complete':
                    return self._read(brand_id, 'plans', prior['plan_id'])
                raise ValueError('该规划已提交或曾中断；为避免重复模型调用，不自动重试')
            request = text_field(payload.get('request', ''), required=True)
            if payload.get('task_id'):
                task = self._read(brand_id, 'tasks', payload['task_id'])
                if request != task['request']:
                    raise ValueError('继续对话时请保留最初的问题；新问题请另开对话')
                if any(p['task_id'] == task['id'] and p['status'] == 'running'
                       for p in self._list(brand_id, 'planning')):
                    raise ValueError('正在处理上一条消息，请等回复后再继续')
            else:
                issue = self._read(brand_id, 'issues', payload['issue_id']) if payload.get('issue_id') else None
                task = {'id': uuid.uuid4().hex, 'brand_id': brand_id,
                        'issue_id': issue['id'] if issue else None,
                        'request': request, 'question': request,
                        'created_by': user['username'], 'created_at': now()}
                if issue:
                    task['issue'] = copy.deepcopy(issue)
            inputs = {k: copy.deepcopy(payload[k]) for k in
                      ('answers', 'task_type', 'mode', 'queries', 'budget', 'sources', 'source_config',
                       'keyword', 'start_date', 'end_date', 'time_window', 'audience', 'exclusions',
                       'hypothesis', 'conversation', 'previous_plan',
                       'proceed_with_assumptions') if k in payload}
            if 'sources' not in inputs and 'source_config' not in inputs:
                inputs['sources'] = copy.deepcopy(brand.get('source_config', {}))
            inputs['use_ai'] = payload.get('use_ai', False)
            snapshot = {k: copy.deepcopy(v) for k, v in brand.items() if k != 'members'}
            # This ledger is written before any optional, explicitly requested AI call.
            operation = {'id': request_id, 'brand_id': brand_id, 'task_id': task['id'],
                         'request_checksum': request_checksum, 'status': 'running',
                         'use_ai': inputs['use_ai'], 'inputs': copy.deepcopy(inputs),
                         'created_by': user['username'],
                         'created_at': now(), 'updated_at': now()}
            self._save(brand_id, 'tasks', task)
            self._pause_schedule(brand_id, task['id'],
                '正在修改研究方案；请确认新方案后重新启用自动执行。')
            self._save(brand_id, 'planning', operation)
        # Provider latency must not block other brands' reads or reviews.
        try:
            generated = research_v2.create_plan(snapshot, task, inputs,
                        run_dir=self._directory(brand_id) / 'planning-runs' / request_id)
            if not isinstance(generated, dict):
                raise ValueError('研究计划格式无效')
            with self.lock:
                self._brand(brand_id, user, 'researcher')
                plan = copy.deepcopy(generated)
                plan.update(id=uuid.uuid4().hex, brand_id=brand_id, task_id=task['id'],
                            issue_id=task['issue_id'], task=task, brand_snapshot=snapshot,
                            delivery_profile=copy.deepcopy(brand['delivery_profile']),
                            status='draft', created_at=now(), updated_at=now(),
                            created_by=user['username'], plan_version=1,
                            planning_request_id=request_id)
                plan['brief'] = {'brand': brand['name'], 'request': task['request'],
                                 'question': plan.get('question', task['request']),
                                 'audience': plan.get('audience', brand.get('audience', '')),
                                 'objective': brand.get('objective', ''), 'task_type': plan.get('task_type', '')}
                plan['assistant_message'] = plan_reply(plan)
                plan['checksum'] = digest(plan)
                self._save(brand_id, 'plans', plan)
                task.update(latest_plan_id=plan['id'], updated_at=now())
                self._save(brand_id, 'tasks', task)
                operation.update(status='complete', plan_id=plan['id'], updated_at=now())
                self._save(brand_id, 'planning', operation)
                self._pause_schedule(brand_id, task['id'],
                    '研究方案已更新；检查新方案后重新启用自动执行。')
                return plan
        except Exception:
            with self.lock:
                operation.update(status='failed', updated_at=now())
                self._save(brand_id, 'planning', operation)
                self._pause_schedule(brand_id, task['id'],
                    '上次研究方案修改未完成；请核对研究方案后重新启用自动执行。')
            raise

    def conversations(self, brand_id, user, task_id=None):
        """Resume brand-owned dialogue without starting any model or source work."""
        with self.lock:
            self._brand(brand_id, user)
            tasks = self._list(brand_id, 'tasks')
            plans = sorted((p for p in self._list(brand_id, 'plans')
                            if not p.get('scheduled_from_plan_id')),
                           key=lambda p: p.get('created_at', ''), reverse=True)
            jobs = self._list(brand_id, 'jobs')
            operations = self._list(brand_id, 'planning')
            events = self._list(brand_id, 'dialogue_events')
            result = []
            for task in tasks:
                if task_id is not None and task['id'] != task_id:
                    continue
                latest = next((p for p in plans if p['task_id'] == task['id']), None)
                job = next((j for j in jobs if j['task_id'] == task['id']
                            and (not latest or j.get('plan_id') == latest['id']
                                 or j.get('schedule_plan_id') == latest['id'])), None)
                operation = next((o for o in operations if o['task_id'] == task['id']), None)
                schedule = self._optional(brand_id, 'schedules', task['id'])
                task_events = [event for event in events if event.get('task_id') == task['id']]
                status = job['status'] if job else ('plan_ready' if latest and latest.get('ready')
                          else 'needs_revision' if latest and latest.get('needs_revision')
                          else 'awaiting_reply' if latest else 'draft')
                item = {'id': task['id'], 'request': task['request'],
                        'title': task.get('title') or task['request'][:150],
                        'schedule': self._public_schedule(schedule),
                        'planning_request_id': operation['id'] if operation else None,
                        'plan_id': latest['id'] if latest else None,
                        'job_id': job['id'] if job else None, 'status': status,
                        'updated_at': max(v.get('updated_at', v.get('created_at', ''))
                                          for v in (task, latest or {}, job or {}, operation or {},
                                                    schedule or {}, *task_events))}
                if task_id is not None:
                    item.update(task=copy.deepcopy(task), plan=copy.deepcopy(latest))
                    transcript = [{'role': 'user', 'content': task['request']}]
                    task_operations = [o for o in operations if o['task_id'] == task['id']]
                    operation_ids = {o['id'] for o in task_operations}
                    timeline = [(o['created_at'], 0, o['id'], 'input', o) for o in task_operations]
                    timeline += [(p['created_at'], 1, p['id'], 'plan', p) for p in plans
                                 if p['task_id'] == task['id']]
                    timeline += [(e['created_at'], 2, e['id'], 'schedule', e) for e in task_events]
                    for _, _, _, kind, event in sorted(timeline):
                        if kind == 'input':
                            inputs = event.get('inputs', {})
                            recent = inputs.get('conversation', [])
                            if isinstance(recent, list):
                                recent = [t for t in recent if isinstance(t, dict) and
                                          t.get('role') in ('user', 'assistant') and isinstance(t.get('content'), str)]
                                transcript = merge_turns(transcript, recent)
                            answer = inputs.get('answers')
                            if isinstance(answer, str) and answer.strip() and (not recent or
                                    recent[-1] != {'role': 'user', 'content': answer}):
                                transcript.append({'role': 'user', 'content': answer})
                        elif kind == 'plan':
                            if event.get('planning_request_id') not in operation_ids:
                                transcript = merge_turns(transcript, event.get('conversation', []))
                            transcript.append({'role': 'assistant', 'content': event.get('assistant_message') or plan_reply(event)})
                        else:
                            transcript.extend(copy.deepcopy(event['turns']))
                    # A failed send retains the user's words; recovery never retries providers.
                    if operation and operation['status'] != 'complete':
                        item['pending'] = {'status': operation['status'],
                            'request_id': operation['id'],
                            'conversation': copy.deepcopy(operation.get('inputs', {}).get('conversation', [])),
                            'answers': operation.get('inputs', {}).get('answers', '')}
                    item['conversation'] = transcript
                result.append(item)
            result.sort(key=lambda item: item['updated_at'], reverse=True)
            if task_id is not None:
                if not result:
                    raise ValueError('记录不存在')
                return result[0]
            return {'conversations': result}

    def confirm(self, payload, user):
        brand_id = identifier(payload.get('brand_id'))
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            plan = self._read(brand_id, 'plans', payload.get('plan_id'))
            if payload.get('checksum') != plan['checksum']:
                raise ValueError('计划已变化，请刷新并重新确认')
            reason = self._plan_revision_reason(brand_id, plan)
            if reason:
                raise ValueError(reason)
            if not plan.get('ready', False):
                raise ValueError('方案还需要调整，请先补充回答或修改设置')
            if plan['status'] == 'draft':
                plan.update(status='confirmed', confirmed_by=user['username'],
                            confirmed_at=now(), updated_at=now())
                self._save(brand_id, 'plans', plan)
            return plan

    def execute(self, payload, user):
        brand_id = identifier(payload.get('brand_id'))
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            plan = self._read(brand_id, 'plans', payload.get('plan_id'))
            job_id = 'plan_' + plan['id']
            existing = self._directory(brand_id) / 'jobs' / (job_id + '.json')
            if existing.exists():
                return self._read(brand_id, 'jobs', job_id)
            active = next((job for job in self._list(brand_id, 'jobs')
                           if job.get('task_id') == plan['task_id'] and job.get('status') in ACTIVE), None)
            if active and active.get('schedule_plan_id') == plan['id']:
                return active
            reason = self._plan_revision_reason(brand_id, plan)
            if reason:
                raise ValueError(reason)
            if active:
                raise ValueError('上一轮仍在执行，请等完成后再开始本轮研究')
            if plan['status'] != 'confirmed':
                raise ValueError('执行前必须确认研究计划')
            job = {'id': job_id, 'run_id': job_id, 'brand_id': brand_id,
                   'task_id': plan['task_id'], 'issue_id': plan.get('issue_id'),
                   'plan_id': plan['id'], 'plan_checksum': plan['checksum'],
                   'title': plan['task']['request'], 'status': 'queued',
                   'created_by': user['username'], 'created_at': now(), 'updated_at': now()}
            # Job is the spend/idempotency record and must exist before the plan update.
            self._save(brand_id, 'jobs', job)
            plan.update(status='executing', job_id=job_id, updated_at=now())
            self._save(brand_id, 'plans', plan)
            self.queue.put((brand_id, job_id))
            return copy.deepcopy(job)

    def _previous(self, brand_id, issue_id):
        if not issue_id:
            return []
        editions = [x for x in self._list(brand_id, 'editions') if x.get('issue_id') == issue_id][:12]
        feedback = self._list(brand_id, 'feedback')
        for edition in editions:
            edition['feedback'] = [item for item in feedback if item.get('job_id') == edition['job_id']]
        return editions

    def _check_scheduled_job(self, brand_id, job_id):
        with self.lock:
            job = self._read(brand_id, 'jobs', job_id)
            if not job.get('schedule_id'):
                return
            schedule = self._optional(brand_id, 'schedules', job['schedule_id'])
            if (not schedule or schedule.get('confirmation_id') != job.get('schedule_confirmation_id')
                    or (not schedule.get('enabled') and schedule.get('status') != 'exhausted')):
                raise ScheduledPauseError('自动执行设置已暂停或变化，本次执行已停止。')
            reason = self._schedule_guard(brand_id, schedule)
            if reason:
                self._pause_schedule(brand_id, schedule['id'], reason)
                raise ScheduledPauseError(reason)

    def _finish_scheduled_job(self, brand_id, job, collected=None):
        if not job.get('schedule_id'):
            return
        run = self._optional(brand_id, 'schedule_runs', job['id'])
        if run:
            run.update(status=job['status'], updated_at=now())
            self._save(brand_id, 'schedule_runs', run)
        schedule = self._optional(brand_id, 'schedules', job['schedule_id'])
        # A previous run may finish after the user confirms a different schedule.
        if not schedule or schedule.get('confirmation_id') != job.get('schedule_confirmation_id'):
            return
        uncertain = False
        if collected:
            records = collected.get('ledger', []) + collected.get('enrichment', {}).get('outcomes', [])
            collection = collected.get('collection', {})
            uncertain = (collection.get('status') == 'failed' or bool(collection.get('errors')) or
                         any(record.get('status') in ('started', 'failed', 'unknown') or
                             isinstance(record.get('errors'), int) and record['errors'] > 0
                             for record in records))
        if job['status'] in ('failed', 'interrupted', 'needs_revision') or uncertain:
            reason = (job.get('error') or '本轮有未完成调用或未通过稿件校验；请核对后重新确认自动执行。')
            self._pause_schedule(brand_id, schedule['id'], reason)

    def _graph(self, brand_id):
        from . import editorial_v2, research_v2
        directory = self._directory(brand_id)
        connection = sqlite3.connect(str(directory / 'checkpoint.sqlite'), check_same_thread=False)
        os.chmod(directory / 'checkpoint.sqlite', 0o600)
        saver = SqliteSaver(connection)

        def collect(state):
            self._check_scheduled_job(brand_id, state['run_id'])
            run_dir = directory / 'runs' / identifier(state['run_id'])
            run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            result = research_v2.collect(state['plan'], run_dir)
            # Persist immediately after collection, independently of later model work.
            self._write(run_dir / 'collection.json', result)
            self._phase(brand_id, state['run_id'], 'editing')
            return {'collected': result, 'status': 'editing'}

        def edit(state):
            self._check_scheduled_job(brand_id, state['run_id'])
            run_dir = directory / 'runs' / identifier(state['run_id'])
            result = editorial_v2.edit(state['plan'], state['collected'],
                                      self._previous(brand_id, state['plan'].get('issue_id')),
                                      run_dir=run_dir)
            return {'delivery': result, 'status': 'validating'}

        def enrich(state):
            self._check_scheduled_job(brand_id, state['run_id'])
            self._phase(brand_id, state['run_id'], 'enriching')
            run_dir = directory / 'runs' / identifier(state['run_id'])
            result = research_v2.enrich(state['plan'], state['collected'], state['delivery'], run_dir)
            self._write(run_dir / 'collection.json', result)
            status = 'reediting' if result['enrichment']['attempted'] else 'validating'
            self._phase(brand_id, state['run_id'], status)
            return {'collected': result, 'status': status}

        def reedit(state):
            self._check_scheduled_job(brand_id, state['run_id'])
            run_dir = directory / 'runs' / identifier(state['run_id'])
            result = editorial_v2.edit(state['plan'], state['collected'],
                       self._previous(brand_id, state['plan'].get('issue_id')), run_dir=run_dir,
                       stage='reedit', prior_model_usage=state['delivery']['model_usage'],
                       previous_draft=state['delivery'])
            return {'delivery': result, 'status': 'validating'}

        def validate(state):
            self._phase(brand_id, state['run_id'], 'validating')
            errors = editorial_v2.validate_edition(
                state['delivery'], state['collected'].get('evidence', []),
                state['plan']['delivery_profile'],
                self._previous(brand_id, state['plan'].get('issue_id')))
            return {'errors': errors, 'status': 'needs_revision' if errors else 'awaiting_review'}

        def human(state):
            decision = interrupt({'brand_id': brand_id, 'run_id': state['run_id'],
                                  'revision_checksum': digest(state['delivery']),
                                  'errors': state.get('errors', [])})
            if decision.get('decision') == 'approve' and state.get('errors'):
                raise ValueError('稿件未通过交付规格检查')
            return {'review': decision,
                    'status': 'approved' if decision.get('decision') == 'approve' else 'rejected'}

        graph = StateGraph(ResearchState)
        for name, fn in [('collect', collect), ('edit', edit), ('enrich_if_needed', enrich),
                         ('reedit', reedit), ('validate', validate), ('human_review', human)]:
            graph.add_node(name, fn)
        graph.add_edge(START, 'collect')
        graph.add_edge('collect', 'edit')
        graph.add_conditional_edges('edit', lambda state: 'enrich_if_needed' if
            state['delivery'].get('enrichment_requests') else 'validate')
        graph.add_conditional_edges('enrich_if_needed', lambda state: 'reedit' if
            state['collected']['enrichment']['attempted'] else 'validate')
        graph.add_edge('reedit', 'validate')
        graph.add_edge('validate', 'human_review')
        graph.add_edge('human_review', END)
        return graph.compile(checkpointer=saver), connection

    def _phase(self, brand_id, job_id, status):
        with self.lock:
            job = self._read(brand_id, 'jobs', job_id)
            job.update(status=status, updated_at=now())
            self._save(brand_id, 'jobs', job)

    def _worker(self):
        while True:
            brand_id, job_id = self.queue.get()
            try:
                self.process_job(brand_id, job_id)
            finally:
                self.queue.task_done()

    def process_job(self, brand_id, job_id):
        with self.lock:
            job = self._read(brand_id, 'jobs', job_id)
            if job['status'] != 'queued':
                return job
            plan = self._read(brand_id, 'plans', job['plan_id'])
            self._phase(brand_id, job_id, 'collecting')
        connection = None
        try:
            graph, connection = self._graph(brand_id)
            config = {'configurable': {'thread_id': job_id}}
            result = graph.invoke({'brand_id': brand_id, 'task_id': job['task_id'],
                                   'run_id': job_id, 'plan': plan}, config)
            with self.lock:
                job = self._read(brand_id, 'jobs', job_id)
                if job['status'] not in {'approved', 'rejected'}:
                    job.update(status=result.get('status', 'awaiting_review'), updated_at=now())
                    self._save(brand_id, 'jobs', job)
                self._finish_scheduled_job(brand_id, job, result.get('collected'))
        except ScheduledPauseError as exc:
            with self.lock:
                job = self._read(brand_id, 'jobs', job_id)
                job.update(status='interrupted', updated_at=now(), error_code='schedule_paused',
                           error=str(exc) + '已发生的调用需要核对，不自动重试。')
                self._save(brand_id, 'jobs', job)
                self._finish_scheduled_job(brand_id, job)
        except Exception:
            with self.lock:
                job = self._read(brand_id, 'jobs', job_id)
                source_failure = job['status'] in ('collecting', 'enriching')
                job.update(status='failed', updated_at=now(),
                           error_code='source_unavailable' if source_failure else 'editorial_incomplete',
                           error=('来源采集未完成，请检查来源授权与配置。' if source_failure else
                                  '证据已保留，编辑稿未完成；请检查模型配置与校验记录。') +
                                 '可能已发生调用，不自动重试；失败不等于没有新信号。')
                self._save(brand_id, 'jobs', job)
                self._finish_scheduled_job(brand_id, job)
        finally:
            if connection:
                connection.close()
        return job

    def job(self, brand_id, key, user):
        with self.lock:
            self._brand(brand_id, user)
            result = self._read(brand_id, 'jobs', key)
            graph, connection = self._graph(brand_id)
            try:
                state = graph.get_state({'configurable': {'thread_id': key}}).values
            finally:
                connection.close()
            collected = state.get('collected', {})
            run_dir = self._directory(brand_id) / 'runs' / identifier(key)
            ledger_path = run_dir / 'source-ledger-v2.json'
            audit_path = run_dir / 'enrichment-attempt-v2.json'
            ledger = json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.is_file() else collected.get('ledger', [])
            enrichment = collected.get('enrichment') or (
                json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.is_file() else {})
            result.update(delivery=state.get('delivery', {}), errors=state.get('errors', []),
                          evidence=collected.get('evidence', []),
                          external_context=collected.get('external_context', []),
                          collection=collected.get('collection', {}), coverage=collected.get('coverage', {}),
                          ledger=ledger, enrichment=enrichment,
                          revision_checksum=digest(state.get('delivery', {})),
                          has_artifact=result['status'] == 'approved', review=state.get('review', {}))
            result['plan'] = self._read(brand_id, 'plans', result['plan_id'])
            return result

    def revise(self, payload, user):
        from . import editorial_v2
        brand_id, job_id = identifier(payload.get('brand_id')), identifier(payload.get('job_id'))
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            job = self.job(brand_id, job_id, user)
            if job['status'] not in ('awaiting_review', 'needs_revision'):
                raise ValueError('当前稿件不可编辑')
            if payload.get('checksum') != job['revision_checksum']:
                raise ValueError('稿件已变化，请刷新后编辑')
            delivery = copy.deepcopy(payload.get('delivery'))
            if not isinstance(delivery, dict) or len(json.dumps(delivery)) > 150000:
                raise ValueError('稿件格式无效')
            errors = editorial_v2.validate_edition(delivery, job['evidence'],
                       job['plan']['delivery_profile'], self._previous(brand_id, job.get('issue_id')))
            audit = {'id': uuid.uuid4().hex, 'brand_id': brand_id, 'job_id': job_id,
                     'created_at': now(), 'editor': user['username'],
                     'before': job['delivery'], 'after': delivery,
                     'before_checksum': job['revision_checksum'], 'after_checksum': digest(delivery)}
            graph, connection = self._graph(brand_id)
            try:
                graph.update_state({'configurable': {'thread_id': job_id}},
                                   {'delivery': delivery, 'errors': errors,
                                    'status': 'needs_revision' if errors else 'awaiting_review'},
                                   as_node='validate')
            finally:
                connection.close()
            self._save(brand_id, 'revisions', audit)
            self._phase(brand_id, job_id, 'needs_revision' if errors else 'awaiting_review')
            return self.job(brand_id, job_id, user)

    def review(self, payload, user):
        from . import editorial_v2
        brand_id, job_id = identifier(payload.get('brand_id')), identifier(payload.get('job_id'))
        with self.lock:
            self._brand(brand_id, user, 'reviewer')
            job = self.job(brand_id, job_id, user)
            if job['status'] not in ('awaiting_review', 'needs_revision'):
                raise ValueError('当前稿件不在审核阶段')
            if payload.get('checksum') != job['revision_checksum']:
                raise ValueError('审核必须对应当前稿件版本')
            decision = payload.get('decision')
            if decision not in ('approve', 'reject'):
                raise ValueError('审核决定无效')
            errors = editorial_v2.validate_edition(job['delivery'], job['evidence'],
                       job['plan']['delivery_profile'], self._previous(brand_id, job.get('issue_id')))
            if decision == 'approve' and errors:
                raise ValueError('稿件未通过交付规格检查：' + '；'.join(errors[:4]))
            review = {'decision': decision, 'reviewer': user['username'],
                      'note': text_field(payload.get('note', ''), 2000),
                      'checksum': job['revision_checksum'], 'reviewed_at': now()}
            graph, connection = self._graph(brand_id)
            try:
                config = {'configurable': {'thread_id': job_id}}
                # A manual revision rewinds to the review node; materialize its interrupt.
                if not graph.get_state(config).interrupts:
                    graph.invoke(None, config)
                state = graph.invoke(Command(resume=review), config)
            finally:
                connection.close()
            if state['status'] == 'approved':
                edition = {'id': job_id, 'brand_id': brand_id, 'job_id': job_id,
                           'issue_id': job.get('issue_id'), 'task_id': job['task_id'],
                           'delivery': job['delivery'], 'delivery_profile': job['plan']['delivery_profile'],
                           'brand_snapshot': job['plan']['brand_snapshot'],
                           'evidence': job['evidence'], 'review': review, 'created_at': now(),
                           'plan_checksum': job['plan_checksum'], 'revision_checksum': job['revision_checksum']}
                self._save(brand_id, 'editions', edition)
            self._phase(brand_id, job_id, state['status'])
            return self.job(brand_id, job_id, user)

    def feedback(self, payload, user):
        brand_id = identifier(payload.get('brand_id'))
        with self.lock:
            self._brand(brand_id, user)
            job = self._read(brand_id, 'jobs', payload.get('job_id'))
            category = payload.get('category')
            if category not in FEEDBACK:
                raise ValueError('反馈类型无效')
            item = {'id': uuid.uuid4().hex, 'brand_id': brand_id, 'job_id': job['id'],
                    'issue_id': job.get('issue_id'), 'category': category,
                    'note': text_field(payload.get('note', ''), 2000),
                    'created_by': user['username'], 'created_at': now()}
            return self._save(brand_id, 'feedback', item)

    def get(self, path, query, user):
        route = path.removeprefix('/api/v2/')
        if route == 'brands':
            return self.brands(user)
        brand_id = identifier(query.get('brand_id'))
        with self.lock:
            brand, roles = self._brand(brand_id, user)
            if route == 'brand':
                return self._public_brand(brand, roles)
            if route == 'conversations':
                return self.conversations(brand_id, user)
            if route == 'conversation':
                return self.conversations(brand_id, user, identifier(query.get('id')))
            if route == 'schedule':
                task_id = identifier(query.get('id') or query.get('task_id'))
                self._read(brand_id, 'tasks', task_id)
                return self._schedule_response(brand_id, task_id)
            if route in ('issues', 'jobs', 'editions', 'feedback', 'tasks'):
                records = self._list(brand_id, route)
                if route == 'jobs' and query.get('task_id'):
                    task_id = identifier(query['task_id'])
                    self._read(brand_id, 'tasks', task_id)
                    records = [j for j in records if j.get('task_id') == task_id]
                return {route: records}
            if route == 'plan':
                return self._read(brand_id, 'plans', query.get('id') or query.get('plan_id'))
            if route == 'job':
                return self.job(brand_id, query.get('id') or query.get('job_id'), user)
            if route == 'artifact':
                from . import editorial_v2
                job = self._read(brand_id, 'jobs', query.get('id') or query.get('job_id'))
                if job['status'] != 'approved':
                    raise ValueError('只有已审核稿件可以导出')
                edition = self._read(brand_id, 'editions', job['id'])
                return {'markdown': editorial_v2.render_markdown(edition['delivery'],
                            edition['evidence'], brand_name=edition.get('brand_snapshot', brand)['name']),
                        'filename': 'signal-deck-' + job['id'] + '.md'}
            if route == 'config':
                return {'brand_id': brand_id, 'roles': roles,
                        'can_research': bool({'admin', 'researcher'} & set(roles)),
                        'can_review': bool({'admin', 'reviewer'} & set(roles)),
                        'can_manage': 'admin' in roles,
                        'ai_configured': all(os.environ.get(k) for k in
                         ('SIGNAL_DESK_AI_BASE_URL', 'SIGNAL_DESK_AI_API_KEY', 'SIGNAL_DESK_AI_MODEL')),
                        'source_config': brand.get('source_config', {}),
                        'delivery_profile': brand['delivery_profile'], 'version': '0.2.1'}
        raise ValueError('没有此接口')

    def post(self, path, payload, user):
        if not isinstance(payload, dict):
            raise ValueError('请求格式无效')
        route = path.removeprefix('/api/v2/')
        if route == 'brands':
            return self.save_brand(payload, user, create=True)
        actions = {'brand': self.save_brand, 'issues': self.save_issue,
                   'plan': self.create_plan, 'confirm': self.confirm,
                   'execute': self.execute, 'revise': self.revise,
                   'review': self.review, 'feedback': self.feedback,
                   'schedule-preview': self.schedule_preview, 'schedule': self.save_schedule,
                   'task-title': self.task_title}
        if route not in actions:
            raise ValueError('没有此接口')
        return actions[route](payload, user)
