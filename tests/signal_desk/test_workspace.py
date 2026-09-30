import json
import pytest
from insightbot.signal_desk.workspace import Workspace


def profile(ws):
    return ws.save_profile({'brand':'Sun Life','question':'What evidence?','keyword':'退休','time_window':'ONE_WEEK','audience':'Families'})

def plan(ws,mode='replay'):
    p=ws.create_plan(profile(ws)['id'],mode)
    return ws.confirm_plan(p['id'],p['checksum'],'Editor')


def test_confirm_before_execute_and_idempotent(tmp_path):
    ws=Workspace(tmp_path,start_worker=False)
    p=ws.create_plan(profile(ws)['id'])
    with pytest.raises(ValueError): ws.execute_plan(p['id'])
    ws.confirm_plan(p['id'],p['checksum'],'Editor')
    first=ws.execute_plan(p['id'])
    assert ws.execute_plan(p['id'])['id']==first['id']
    assert len(ws.jobs())==1


def test_restart_marks_uncertain_without_retry(tmp_path):
    ws=Workspace(tmp_path,start_worker=False)
    p=plan(ws)
    j=ws.execute_plan(p['id'])
    second=Workspace(tmp_path,start_worker=False)
    assert second.job(j['id'])['status']=='interrupted'
    assert second.execute_plan(p['id'])['status']=='interrupted'


def test_replay_review_revision_audit(tmp_path, monkeypatch):
    evidence=[{'source_id':'a','platform':'test','url':'https://example.org/a','title':'Fixture','excerpt':'Fixture body'}]
    cards=[{'title':'Fixture','disposition':'research','observation':'Observation','interpretation':'Interpretation','brand_relevance':'Relevance','limitations':'Limit','next_step':'Research','evidence_ids':['a'],'counter_evidence_ids':[]}]
    sample=tmp_path/'sample.json'
    sample.write_text(json.dumps({'brief':{'brand':'Sun Life','question':'Original question'},'evidence':evidence,'replay_cards':cards}))
    monkeypatch.setenv('SIGNAL_DESK_INPUT_FILE',str(sample))
    ws=Workspace(tmp_path/'state',start_worker=False)
    p=plan(ws)
    job=ws.execute_plan(p['id'])
    assert ws.process_job(job['id'])['status']=='awaiting_review'
    state=ws.run(job['id'])
    old=state['revision_checksum']
    assert 'artifact' not in state
    state['cards'][0]['title']='Edited title'
    revised=ws.revise(job['id'],state['cards'],old,'Editor')
    with pytest.raises(ValueError): ws.review(job['id'],'approve','Editor',checksum=old)
    approved=ws.review(job['id'],'approve','Editor',checksum=revised['revision_checksum'])
    assert approved['status']=='delivered_local'
    assert approved['cards'][0]['title']=='Edited title'
    audit=json.loads(next((ws.base/'revisions').glob('*.json')).read_text())
    assert audit['before_cards'][0]['title']=='Fixture'
    assert audit['after_cards'][0]['title']=='Edited title'
    assert ws.jobs()[0]['status']=='delivered_local'


def test_failure_redaction_and_no_retry(tmp_path,monkeypatch):
    import insightbot.signal_desk.workspace as module
    for name in ('JUSTONEAPI_TOKEN','SIGNAL_DESK_AI_BASE_URL','SIGNAL_DESK_AI_API_KEY','SIGNAL_DESK_AI_MODEL'): monkeypatch.setenv(name,'test')
    calls=[]
    def fail(*a):
        calls.append(1)
        raise RuntimeError('https://secret/?token=private')
    monkeypatch.setattr(module,'justone_search',fail)
    ws=Workspace(tmp_path,start_worker=False)
    p=plan(ws,'live');j=ws.execute_plan(p['id'])
    result=ws.process_job(j['id'])
    assert result['status']=='failed'
    assert 'private' not in json.dumps(result)
    ws.process_job(j['id'])
    assert len(calls)==1


def test_profile_snapshot_and_budget(tmp_path):
    ws=Workspace(tmp_path,start_worker=False)
    p=profile(ws);research=ws.create_plan(p['id'])
    p['question']='Changed'
    ws.save_profile(p)
    confirmed=ws.confirm_plan(research['id'],research['checksum'],'Editor')
    assert confirmed['brief']['question']=='What evidence?'
    assert confirmed['budget']=={'search_calls':1,'max_samples':20,'ai_calls':1}


def test_job_written_before_plan_crash_does_not_duplicate(tmp_path,monkeypatch):
    ws=Workspace(tmp_path,start_worker=False)
    p=plan(ws)
    original=ws._save
    def crash(kind,value):
        if kind=='plans' and value.get('job_id'): raise RuntimeError('simulated crash')
        return original(kind,value)
    monkeypatch.setattr(ws,'_save',crash)
    with pytest.raises(RuntimeError): ws.execute_plan(p['id'])
    second=Workspace(tmp_path,start_worker=False)
    recovered=second.execute_plan(p['id'])
    assert recovered['status']=='interrupted'
    assert len(second.jobs())==1


def test_invalid_revision_reference_preserves_original(tmp_path):
    ws=Workspace(tmp_path,start_worker=False)
    original=ws._desk.start('legacy',{'brand':'A','question':'Q'},[{'url':'https://example.org/a','excerpt':'Fixture'}])
    current=ws.run('legacy')
    current['cards'][0]['evidence_ids']=['invented']
    with pytest.raises(ValueError): ws.revise('legacy',current['cards'],current['revision_checksum'],'Editor')
    assert ws.run('legacy')['cards']==original['cards']
    assert not list((ws.base/'revisions').glob('*.json'))


@pytest.mark.parametrize('decision,expected',[('approve','delivered_local'),('reject','rejected')])
def test_worker_final_save_preserves_concurrent_review(tmp_path,monkeypatch,decision,expected):
    from insightbot.signal_desk.core import Desk
    sample=tmp_path/'sample.json'
    sample.write_text(json.dumps({'brief':{'brand':'Sun Life','question':'Original'},'evidence':[],'replay_cards':[]}))
    monkeypatch.setenv('SIGNAL_DESK_INPUT_FILE',str(sample))
    ws=Workspace(tmp_path/'state',start_worker=False)
    p=plan(ws)
    job=ws.execute_plan(p['id'])
    real_start=Desk.start
    def start_then_review(desk,*args,**kwargs):
        stale_result=real_start(desk,*args,**kwargs)
        current=ws.run(job['id'])
        ws.review(job['id'],decision,'Editor',checksum=current['revision_checksum'])
        return stale_result
    monkeypatch.setattr(Desk,'start',start_then_review)
    assert ws.process_job(job['id'])['status']==expected
    assert ws.job(job['id'])['status']==expected
    assert ws.run(job['id'])['status']==expected
