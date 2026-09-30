"""File-backed business workspace for the single-user Signal Desk test environment."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import queue
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .core import Desk, validate_cards
from .providers import justone_search, search_to_input


def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value): raise ValueError('Invalid identifier')
    return value


class Workspace:
    def __init__(self, root, start_worker=True):
        self.root = Path(root).resolve()
        self.base = self.root / 'workspace'
        for folder in ('profiles','plans','jobs','revisions','inputs'):
            (self.base / folder).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        self._desk = Desk(self.root)
        for job in self._list('jobs'):
            if job['status'] in ('queued','running','collecting','editing'):
                job.update(status='interrupted', error='服务曾中断；可能已有付费请求，不自动重试。', updated_at=now())
                self._save('jobs', job)
        if start_worker:
            self.worker = threading.Thread(target=self._worker, daemon=True, name='signal-desk-workspace')
            self.worker.start()

    def _save(self, kind, value):
        path = self.base / kind / (identifier(value['id']) + '.json')
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.chmod(0o600)
        os.replace(temp, path)
        return copy.deepcopy(value)

    def _read(self, kind, key):
        path = self.base / kind / (identifier(key) + '.json')
        if not path.exists(): raise ValueError('Record not found')
        return json.loads(path.read_text())

    def _list(self, kind):
        return sorted([json.loads(p.read_text()) for p in (self.base / kind).glob('*.json')], key=lambda x:x.get('updated_at',''), reverse=True)

    def save_profile(self, payload):
        fields = ('brand','question','audience','hypothesis','topics','exclusions','time_window','keyword')
        profile = {'id':identifier(payload.get('id') or uuid.uuid4().hex)}
        for field in fields:
            value = payload.get(field, '')
            if isinstance(value,list): value = '\n'.join(str(x) for x in value)
            if not isinstance(value,str) or len(value) > 4000: raise ValueError('Invalid brief field')
            profile[field] = value.strip()
        if not all(profile[k] for k in ('brand','question','keyword')): raise ValueError('Brand, question and keyword are required')
        if profile['time_window'] not in ('','ONE_DAY','ONE_WEEK','HALF_YEAR'): raise ValueError('Invalid time window')
        profile['updated_at'] = now()
        with self.lock: return self._save('profiles',profile)

    def profiles(self):
        with self.lock: return self._list('profiles')

    def create_plan(self, profile_id, mode='live'):
        if mode not in ('live','replay'): raise ValueError('Invalid research mode')
        with self.lock:
            profile = self._read('profiles',profile_id)
            plan = {'id':uuid.uuid4().hex,'profile_id':profile_id,'mode':mode,'status':'draft',
                    'brief':{k:v for k,v in profile.items() if k not in ('id','updated_at')},
                    'queries':[profile['keyword']], 'budget':{'search_calls':1 if mode=='live' else 0,'max_samples':20,'ai_calls':1 if mode=='live' else 0},
                    'limitations':['小红书检索样本，不代表全量或目标人群身份。','时间筛选不精确；一页结果按供应商返回顺序最多取20条。'],
                    'created_at':now(),'updated_at':now()}
            plan['provenance'] = '实时采集与 AI 编辑，按确认预算执行。' if mode == 'live' else '人工编辑的历史试跑回放；保留样本原品牌、原问题与历史证据，不生成新研究结论。'
            if mode == 'replay':
                plan['limitations'].append('回放不使用本次关键词重新采集；本次受众、话题与排除项不会重新编辑历史结论。')
            plan['checksum'] = digest(plan)
            return self._save('plans',plan)

    def confirm_plan(self, plan_id, checksum, reviewer):
        if not isinstance(reviewer,str) or not reviewer.strip(): raise ValueError('Confirmation name required')
        with self.lock:
            plan = self._read('plans',plan_id)
            if checksum != plan['checksum']: raise ValueError('Plan changed; refresh before confirming')
            if plan['status'] == 'draft':
                plan.update(status='confirmed', confirmed_by=reviewer.strip(), confirmed_at=now(), updated_at=now())
                self._save('plans',plan)
            return plan

    def execute_plan(self, plan_id):
        with self.lock:
            plan = self._read('plans',plan_id)
            if plan.get('job_id'): return self._read('jobs',plan['job_id'])
            if plan['status'] != 'confirmed': raise ValueError('Confirm the research plan before execution')
            # Deterministic ID prevents a crash between job write and plan write duplicating spend.
            run_id = 'plan_' + plan_id
            path = self.base / 'jobs' / (run_id+'.json')
            if path.exists(): return self._read('jobs',run_id)
            job = {'id':run_id,'run_id':run_id,'plan_id':plan_id,'brand':plan['brief']['brand'],'mode':plan['mode'],
                   'status':'queued','created_at':now(),'updated_at':now()}
            self._save('jobs',job)
            plan.update(job_id=run_id,status='executing',updated_at=now())
            self._save('plans',plan)
            self.queue.put(run_id)
            return job

    def _worker(self):
        while True:
            key = self.queue.get()
            try: self.process_job(key)
            finally: self.queue.task_done()

    def process_job(self, key):
        with self.lock:
            job = self._read('jobs',key)
            if job['status'] != 'queued': return job
            job.update(status='collecting' if job['mode']=='live' else 'editing',updated_at=now())
            self._save('jobs',job)
            plan = self._read('plans',job['plan_id'])
        desk = Desk(self.root)
        try:
            if plan['mode'] == 'live':
                required = ('JUSTONEAPI_TOKEN','SIGNAL_DESK_AI_BASE_URL','SIGNAL_DESK_AI_API_KEY','SIGNAL_DESK_AI_MODEL')
                if not all(os.environ.get(k) for k in required): raise ValueError('Credentials missing')
                raw = justone_search(plan['queries'][0],plan['brief']['time_window'] or None)
                payload = search_to_input(raw,plan['brief']['brand'],plan['brief']['question'])
                payload['collection']['sample_limit'] = 20
                payload['collection']['omitted_by_limit'] = max(0,len(payload['evidence'])-20)
                payload['evidence'] = payload['evidence'][:20]
                payload['brief'] = plan['brief']
            else:
                sample = os.environ.get('SIGNAL_DESK_INPUT_FILE')
                if not sample: raise ValueError('Replay input not configured')
                payload = json.loads(Path(sample).read_text())
                # Replay is tied to its original brief; do not relabel findings as another brand.
                if payload['brief']['brand'] != plan['brief']['brand']: raise ValueError('Replay brand mismatch')
            with self.lock:
                self._save('inputs', {'id':key, 'payload':payload, 'created_at':now()})
                job.update(status='editing', updated_at=now())
                self._save('jobs',job)
            result = desk.start(key,payload['brief'],payload['evidence'],plan['mode'],payload.get('replay_cards',[]),payload.get('collection',{}))
            job.update(status=result['status'],updated_at=now())
        except Exception:
            job.update(status='failed',updated_at=now(),error='研究未完成，请检查配置、供应商权限或输入。付费请求可能已发生；不会自动重试。')
        finally:
            desk.connection.close()
        with self.lock:
            # HTTP review may complete between graph interrupt and this worker save.
            # Reconcile under the same lock used by review so stale results cannot
            # move an approved/rejected job back to awaiting_review.
            persisted = self._read('jobs',key)
            if persisted['status'] in ('delivered_local','rejected'):
                return persisted
            current = self._desk.status(key)
            if current.get('status') in ('awaiting_review','delivered_local','rejected'):
                job['status'] = current['status']
                job.pop('error',None)
            return self._save('jobs',job)

    def job(self, key):
        with self.lock: return self._read('jobs',key)

    def jobs(self):
        with self.lock:
            jobs = self._list('jobs')
            seen = {j['id'] for j in jobs}
            for path in (self.root/'runs').glob('*'):
                if path.is_dir() and path.name not in seen:
                    try:
                        state = self._desk.status(path.name)
                        if state: jobs.append({'id':path.name,'run_id':path.name,'brand':state.get('brief',{}).get('brand',''), 'mode':state.get('mode'), 'status':state.get('status'),'legacy':True})
                    except Exception: pass
            return jobs

    def run(self, key):
        with self.lock:
            state = self._desk.status(identifier(key))
            state['has_artifact'] = bool(state.pop('artifact',None))
            state['revision_checksum'] = digest(state.get('cards',[]))
            state['run_id'] = key
            return state

    def revise(self, key, cards, checksum, reviewer):
        if not isinstance(reviewer,str) or not reviewer.strip(): raise ValueError('Reviewer required')
        with self.lock:
            state = self._desk.status(identifier(key))
            if state.get('status') != 'awaiting_review': raise ValueError('Run is not awaiting review')
            if checksum != digest(state.get('cards',[])): raise ValueError('Cards changed; refresh before editing')
            validate_cards(cards,state['evidence'])
            revision = {'id':uuid.uuid4().hex,'run_id':key,'reviewer':reviewer,'created_at':now(),
                        'before_checksum':checksum,'after_checksum':digest(cards),'before_cards':state['cards'],'after_cards':cards}
            self._save('revisions',revision)
            self._desk.graph.update_state({'configurable':{'thread_id':key}}, {'cards':copy.deepcopy(cards)}, as_node='quality')
            return self.run(key)

    def review(self,key,decision,reviewer,note='',checksum=None):
        with self.lock:
            state = self._desk.status(identifier(key))
            if checksum is None or checksum != digest(state.get('cards',[])): raise ValueError('Review requires current card checksum')
            result = self._desk.resume(key,decision,reviewer,note)
            path = self.base/'jobs'/(key+'.json')
            if path.exists():
                job = self._read('jobs',key)
                job.update(status=result['status'],updated_at=now())
                self._save('jobs',job)
            return self.run(key)
