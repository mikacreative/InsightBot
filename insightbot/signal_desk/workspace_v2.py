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

DEFAULT_DELIVERY = copy.deepcopy(DELIVERY_DEFAULTS)
ROLES = {'admin', 'researcher', 'reviewer'}
KINDS = ('issues', 'tasks', 'plans', 'jobs', 'editions', 'feedback', 'revisions', 'planning')
ACTIVE = {'queued', 'collecting', 'editing', 'validating', 'running'}
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


class WorkspaceV2:
    def __init__(self, root, start_worker=True):
        self.root = Path(root).resolve()
        self.base = self.root / 'v2'
        self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        # Mark uncertainty explicitly; do not rerun providers on service startup.
        for directory in self.base.iterdir():
            if not directory.is_dir() or not (directory / 'brand.json').exists():
                continue
            for job in self._list(directory.name, 'jobs'):
                if job.get('status') in ACTIVE:
                    job.update(status='interrupted', updated_at=now(),
                               error='服务曾中断，可能已有数据或模型调用；不会自动重试。')
                    self._save(directory.name, 'jobs', job)
        if start_worker:
            self.worker = threading.Thread(target=self._worker, daemon=True,
                                           name='signal-desk-v2')
            self.worker.start()

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
            issue = self._read(brand_id, 'issues', payload['issue_id']) if payload.get('issue_id') else None
            task = {'id': uuid.uuid4().hex, 'brand_id': brand_id,
                    'issue_id': issue['id'] if issue else None,
                    'request': text_field(payload.get('request', ''), required=True),
                    'created_by': user['username'], 'created_at': now()}
            task['question'] = task['request']
            if issue:
                task['issue'] = copy.deepcopy(issue)
            inputs = {k: copy.deepcopy(payload[k]) for k in
                      ('answers', 'task_type', 'queries', 'budget', 'sources', 'source_config',
                       'keyword', 'start_date', 'end_date', 'time_window', 'audience', 'exclusions',
                       'hypothesis', 'conversation') if k in payload}
            if 'sources' not in inputs and 'source_config' not in inputs:
                inputs['sources'] = copy.deepcopy(brand.get('source_config', {}))
            inputs['use_ai'] = payload.get('use_ai', False)
            snapshot = {k: copy.deepcopy(v) for k, v in brand.items() if k != 'members'}
            # This ledger is written before any optional, explicitly requested AI call.
            operation = {'id': request_id, 'brand_id': brand_id, 'task_id': task['id'],
                         'request_checksum': request_checksum, 'status': 'running',
                         'use_ai': inputs['use_ai'], 'created_by': user['username'],
                         'created_at': now(), 'updated_at': now()}
            self._save(brand_id, 'tasks', task)
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
                plan['checksum'] = digest(plan)
                self._save(brand_id, 'plans', plan)
                operation.update(status='complete', plan_id=plan['id'], updated_at=now())
                self._save(brand_id, 'planning', operation)
                return plan
        except Exception:
            with self.lock:
                operation.update(status='failed', updated_at=now())
                self._save(brand_id, 'planning', operation)
            raise

    def confirm(self, payload, user):
        brand_id = identifier(payload.get('brand_id'))
        with self.lock:
            self._brand(brand_id, user, 'researcher')
            plan = self._read(brand_id, 'plans', payload.get('plan_id'))
            if payload.get('checksum') != plan['checksum']:
                raise ValueError('计划已变化，请刷新并重新确认')
            if not plan.get('ready', False):
                raise ValueError('请先回答影响研究范围的问题')
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

    def _graph(self, brand_id):
        from . import editorial_v2, research_v2
        directory = self._directory(brand_id)
        connection = sqlite3.connect(str(directory / 'checkpoint.sqlite'), check_same_thread=False)
        os.chmod(directory / 'checkpoint.sqlite', 0o600)
        saver = SqliteSaver(connection)

        def collect(state):
            run_dir = directory / 'runs' / identifier(state['run_id'])
            run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            result = research_v2.collect(state['plan'], run_dir)
            # Persist immediately after collection, independently of later model work.
            self._write(run_dir / 'collection.json', result)
            self._phase(brand_id, state['run_id'], 'editing')
            return {'collected': result, 'status': 'editing'}

        def edit(state):
            run_dir = directory / 'runs' / identifier(state['run_id'])
            result = editorial_v2.edit(state['plan'], state['collected'],
                                      self._previous(brand_id, state['plan'].get('issue_id')),
                                      run_dir=run_dir)
            return {'delivery': result, 'status': 'validating'}

        def validate(state):
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
        for name, fn in [('collect', collect), ('edit', edit), ('validate', validate), ('human_review', human)]:
            graph.add_node(name, fn)
        graph.add_edge(START, 'collect')
        graph.add_edge('collect', 'edit')
        graph.add_edge('edit', 'validate')
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
        except Exception:
            with self.lock:
                job = self._read(brand_id, 'jobs', job_id)
                source_failure = job['status'] == 'collecting'
                job.update(status='failed', updated_at=now(),
                           error_code='source_unavailable' if source_failure else 'editorial_incomplete',
                           error=('来源采集未完成，请检查来源授权与配置。' if source_failure else
                                  '证据已保留，编辑稿未完成；请检查模型配置与校验记录。') +
                                 '可能已发生调用，不自动重试；失败不等于没有新信号。')
                self._save(brand_id, 'jobs', job)
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
            result.update(delivery=state.get('delivery', {}), errors=state.get('errors', []),
                          evidence=collected.get('evidence', []),
                          external_context=collected.get('external_context', []),
                          collection=collected.get('collection', {}), coverage=collected.get('coverage', {}),
                          ledger=collected.get('ledger', []),
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
            if route in ('issues', 'jobs', 'editions', 'feedback', 'tasks'):
                return {route: self._list(brand_id, route)}
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
                   'review': self.review, 'feedback': self.feedback}
        if route not in actions:
            raise ValueError('没有此接口')
        return actions[route](payload, user)
