"""Local-only review workbench. No outbound delivery endpoints."""
import html
import json
import os
import secrets
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from .core import Desk

PAGE = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Signal Desk · Test</title>
<style>*{box-sizing:border-box}body{background:#f4f3ef;color:#172b2b;font:16px system-ui;margin:40px auto;padding:0 20px;max-width:1040px}h1{font-size:42px}textarea,input,select,button{font:inherit;padding:10px;margin:6px 0;border:1px solid #abc;border-radius:6px}textarea{width:97%;height:220px}button{background:#173f3e;color:white;cursor:pointer}pre{white-space:pre-wrap;background:white;padding:22px;border-radius:10px}small{color:#586b6b}.row{display:flex;flex-wrap:wrap;gap:12px;align-items:center}input{max-width:100%}article,pre{overflow-wrap:anywhere}#error{color:#9a3020;white-space:pre-wrap}a{color:#176b65}</style>
<h1>Signal Desk <small>TEST</small></h1><p>外部证据 → 编辑判断 → 人工审稿 → 本地交付</p>
<p>此环境不发送邮件或企微消息。Demo 为演示，Replay 为人工编辑的历史试跑，Live 才调用 AI。</p>
<div id="config"></div><button onclick="sample()">加载已部署的 Sun Life 试跑</button><h2>运行一轮</h2><p>导入 JSON：brief（brand/question/time_window）、evidence 数组；Replay 另含 replay_cards。</p>
<textarea id="input" placeholder='{"brief":{"brand":"Sun Life","question":"品牌假设是否得到支持？"},"evidence":[]}'></textarea>
<div class="row"><select id="mode"><option value="demo">Demo 演示</option><option value="replay">Replay 历史试跑</option><option value="live">Live AI 编辑</option></select><button onclick="start()">开始</button></div>
<h2>审稿台</h2><input id="runid" placeholder="Run ID"><button onclick="load()">加载</button>
<div class="row"><input id="reviewer" placeholder="审稿人姓名"><input id="note" placeholder="审稿意见"><button onclick="review('approve')">批准本地测试稿</button><button onclick="review('reject')">否决</button></div>
<p id="error" role="alert"></p><div id="cards"></div><details><summary>运行详情 JSON</summary><pre id="output">等待运行或加载已有 Run ID。</pre></details><script>
const csrf='__CSRF__';const $=id=>document.getElementById(id);
async function request(path,data){$('error').textContent='';let r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','X-Signal-Desk-CSRF':csrf},body:data?JSON.stringify(data):undefined});let j=await r.json();if(j.run_id)$('runid').value=j.run_id;if(j.cards)renderCards(j);$('output').textContent=JSON.stringify(j,null,2);if(!r.ok){$('error').textContent=j.error;throw Error(j.error)};return j}
function renderCards(s){const root=$('cards');root.replaceChildren();let status=document.createElement('p');status.textContent='模式：'+s.mode+' / 状态：'+s.status;root.append(status);for(const c of s.cards){let card=document.createElement('article');card.style.cssText='background:white;padding:24px;margin:16px 0;border-radius:12px';let h=document.createElement('h2');h.textContent=c.title+' · '+({action:'建议行动',research:'继续研究',observe:'持续观察',drop:'舍弃'}[c.disposition]||c.disposition);card.append(h);for(const [k,label] of Object.entries({observation:'观察',interpretation:'解释',brand_relevance:'品牌相关性',limitations:'证据边界',next_step:'下一步'})){let p=document.createElement('p');p.textContent=label+'：'+c[k];card.append(p)}for(const id of [...c.evidence_ids,...(c.counter_evidence_ids||[])]){let e=s.evidence.find(x=>x.id===id);if(e){let a=document.createElement('a');a.textContent=e.title+' ['+id+']';a.href=e.url;a.target='_blank';a.rel='noopener noreferrer';card.append(a,document.createElement('br'))}}root.append(card)}if(s.artifact){let a=document.createElement('a');a.textContent='下载已批准 Markdown';a.href='/api/artifact?id='+encodeURIComponent($('runid').value);a.download='signal-desk.md';root.append(a)}}
async function sample(){try{let p=await request('/api/sample');$('input').value=JSON.stringify(p,null,2);$('mode').value='replay'}catch(e){}}
async function start(){try{let p=JSON.parse($('input').value);p.mode=$('mode').value;let r=await request('/api/run',p);$('runid').value=r.run_id}catch(e){$('error').textContent=e.message}}
async function load(){try{await request('/api/status?id='+encodeURIComponent($('runid').value))}catch(e){}}
async function review(decision){try{await request('/api/review',{run_id:$('runid').value,decision,reviewer:$('reviewer').value,note:$('note').value})}catch(e){}}
fetch('/api/config').then(r=>r.json()).then(j=>$('config').textContent='AI：'+(j.ai_configured?'已配置':'未配置')+' · JustOneAPI：'+(j.justoneapi_configured?'已配置':'未配置')+' · 交付：仅本地导出');
</script>'''


def serve(root, host='127.0.0.1', port=18876):
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Test service must bind to loopback; use an SSH tunnel')
    desk = Desk(root)
    csrf = secrets.token_urlsafe(32)
    workflow_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, payload, code=200, content_type='application/json'):
            data = (json.dumps(payload, ensure_ascii=False) if content_type == 'application/json' else payload).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path)
            try:
                if path.path == '/':
                    self.send(PAGE.replace('__CSRF__', csrf), content_type='text/html')
                elif path.path == '/health':
                    self.send({'status': 'ok', 'service': 'signal-desk', 'delivery': 'local-only'})
                elif path.path == '/api/config':
                    self.send({'ai_configured': all(os.environ.get(k) for k in ['SIGNAL_DESK_AI_BASE_URL','SIGNAL_DESK_AI_API_KEY','SIGNAL_DESK_AI_MODEL']),
                               'justoneapi_configured': bool(os.environ.get('JUSTONEAPI_TOKEN')), 'collection': 'JSON import / explicit CLI collect and detail', 'outbound_delivery': False})
                elif path.path == '/api/artifact':
                    from pathlib import Path
                    state = desk.status(parse_qs(path.query).get('id',[''])[0])
                    if state.get('status') != 'delivered_local':
                        self.send({'error':'No approved artifact'},404)
                    else:
                        self.send(Path(state['artifact']).read_text(), content_type='text/markdown')
                elif path.path == '/api/sample':
                    from pathlib import Path
                    sample_path = os.environ.get('SIGNAL_DESK_INPUT_FILE')
                    self.send(json.loads(Path(sample_path).read_text()) if sample_path else {'brief': {'brand': 'Sun Life', 'question': '试跑输入尚未配置'}, 'evidence': []})
                elif path.path == '/api/status':
                    self.send(desk.status(parse_qs(path.query).get('id',[''])[0]))
                else:
                    self.send({'error':'not found'},404)
            except (ValueError, KeyError):
                self.send({'error':'Invalid run ID or request'},400)

        def do_POST(self):
            with workflow_lock:
                self.handle_post()

        def handle_post(self):
            if self.headers.get('X-Signal-Desk-CSRF') != csrf:
                self.send({'error':'CSRF validation failed'},403); return
            length = int(self.headers.get('Content-Length', '0'))
            if length > 1000000:
                self.send({'error':'Input too large'},413); return
            run_id = None
            try:
                payload = json.loads(self.rfile.read(length))
                if self.path == '/api/run':
                    run_id = uuid.uuid4().hex
                    result = desk.start(run_id, payload['brief'], payload['evidence'], payload.get('mode','demo'), payload.get('replay_cards', []), payload.get('collection', {}))
                    self.send({'run_id':run_id, **result})
                elif self.path == '/api/review':
                    self.send(desk.resume(payload['run_id'], payload['decision'], payload['reviewer'], payload.get('note','')))
                else:
                    self.send({'error':'not found'},404)
            except Exception as exc:
                # Provider transport errors can embed credentials; never expose exception text.
                self.send({'error':f'Workflow failed ({type(exc).__name__}); check configuration/input. No automatic retry.', 'run_id':run_id},400)

    print(f'Signal Desk test UI: http://{host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
