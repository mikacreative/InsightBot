"""Authenticated internal team test server; loopback plus optional private HTTPS."""
import ipaddress
import json
import os
import ssl
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .auth import Auth, RateLimitError
from .workspace import Workspace
from .workspace_v2 import WorkspaceV2
from .authorization import AuthorizationError


def serve(root, host='127.0.0.1', port=18876):
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('Primary listener must remain loopback')
    root = Path(root).resolve()
    auth = Auth(root)
    workspace = Workspace(root, start_worker=False)
    workspace_v2 = WorkspaceV2(root)
    mutation_lock = threading.RLock()
    lan = os.environ.get('SIGNAL_DESK_LAN_HOST', '')
    tls_port = int(os.environ.get('SIGNAL_DESK_TLS_PORT', '18878'))
    allowed_hosts = {'127.0.0.1', 'localhost', 'mika-macmini.local'}
    if lan:
        address = ipaddress.ip_address(lan)
        if not address.is_private or address.is_unspecified or address.is_loopback:
            raise ValueError('LAN listener requires a specific private interface IP')
        allowed_hosts.add(lan)
    ui = Path(__file__).with_name('ui_v2.html').read_text()
    legacy_ui = Path(__file__).with_name('ui.html').read_text().replace('<body>', '<body><div style="padding:12px;background:#fff4cc;color:#243b40">旧版历史记录 · 仅管理员只读。请返回 <a href="/">0.2 品牌工作区</a> 开始新研究。</div>', 1)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_):
            pass

        def send(self, payload, code=200, content_type='application/json', cookie=None):
            data = (json.dumps(payload, ensure_ascii=False) if content_type == 'application/json' else payload).encode()
            self.send_response(code)
            for name,value in [('Content-Type',content_type+'; charset=utf-8'),('Content-Length',str(len(data))),
                               ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),
                               ('X-Frame-Options','DENY'),('Referrer-Policy','same-origin')]:
                self.send_header(name,value)
            if cookie: self.send_header('Set-Cookie',cookie)
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError): pass

        def valid_host(self):
            try:
                return urlparse('//'+self.headers.get('Host','')).hostname in allowed_hosts
            except ValueError: return False

        def token(self):
            try:
                jar=SimpleCookie(); jar.load(self.headers.get('Cookie',''))
                return jar['sd_session'].value if 'sd_session' in jar else ''
            except Exception: return ''

        def cookie(self, token='', clear=False):
            secure='; Secure' if isinstance(self.connection,ssl.SSLSocket) else ''
            return f'sd_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else 28800}{secure}'

        def do_GET(self):
            if not self.valid_host(): self.send({'error':'无效访问地址'},403); return
            path=urlparse(self.path); query=parse_qs(path.query)
            if path.path=='/health': self.send({'status':'ok','service':'signal-desk','version':'0.2.1','authentication':True,'delivery':'local-only'}); return
            if path.path=='/': self.send(ui,content_type='text/html'); return
            user=auth.session(self.token())
            if not user: self.send({'error':'请先登录'},401); return
            try:
                if path.path.startswith('/api/v2/'):
                    result = workspace_v2.get(path.path, {k:v[0] for k,v in query.items()}, user)
                    self.send(result)
                    return
                if path.path=='/legacy':
                    if user['role']!='admin': self.send({'error':'仅管理员可查看旧版记录'},403); return
                    self.send(legacy_ui,content_type='text/html'); return
                if path.path not in ('/api/me','/api/users','/api/config') and user['role']!='admin':
                    self.send({'error':'旧版共享记录仅供管理员查看'},403); return
                if path.path=='/api/me':
                    self.send({k:user[k] for k in ('username','role','csrf')})
                elif path.path=='/api/profiles': self.send(workspace.profiles())
                elif path.path=='/api/jobs': self.send(workspace.jobs())
                elif path.path=='/api/job': self.send(workspace.job(query.get('id',[''])[0]))
                elif path.path=='/api/status': self.send(workspace.run(query.get('id',[''])[0]))
                elif path.path=='/api/config':
                    self.send({'ai_configured':all(os.environ.get(k) for k in ('SIGNAL_DESK_AI_BASE_URL','SIGNAL_DESK_AI_API_KEY','SIGNAL_DESK_AI_MODEL')),
                               'justoneapi_configured':bool(os.environ.get('JUSTONEAPI_TOKEN')),'delivery':'local-only'})
                elif path.path=='/api/users' and user['role']=='admin': self.send(auth.users())
                elif path.path=='/api/artifact':
                    state=workspace.run(query.get('id',[''])[0])
                    if state.get('status')!='delivered_local': self.send({'error':'尚无已批准稿件'},404)
                    else:
                        from .core import render, render_marketing
                        view=query.get('view',['review'])[0]
                        self.send((render_marketing if view=='marketing' else render)(state),content_type='text/markdown')
                else: self.send({'error':'没有此页面或无权限'},404)
            except PermissionError:
                self.send({'error':'无权访问该品牌或记录'},403)
            except (ValueError, KeyError):
                self.send({'error':'记录或参数无效，请刷新后重试'},400)
            except Exception:
                self.send({'error':'无法读取该记录，请刷新后重试'},400)

        def do_POST(self):
            if not self.valid_host(): self.send({'error':'无效访问地址'},403); return
            origin=self.headers.get('Origin')
            expected=('https' if isinstance(self.connection,ssl.SSLSocket) else 'http')+'://'+self.headers.get('Host','')
            if origin and origin!=expected: self.send({'error':'请求来源不匹配'},403); return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>1000000: self.send({'error':'请求大小无效'},413); return
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict): raise ValueError()
            except Exception: self.send({'error':'输入格式无效'},400); return
            if self.path=='/api/login':
                try: user=auth.authenticate(payload.get('username',''),payload.get('password',''),self.client_address[0])
                except RateLimitError: self.send({'error':'登录尝试过多，请稍后重试'},429); return
                if not user: self.send({'error':'账号或密码错误'},401); return
                self.send({k:user[k] for k in ('username','role','csrf')},cookie=self.cookie(user['token'])); return
            user=auth.session(self.token())
            if not user: self.send({'error':'请先登录'},401); return
            import hmac
            if not hmac.compare_digest(self.headers.get('X-Signal-Desk-CSRF',''),user['csrf']):
                self.send({'error':'登录状态已更新，请刷新页面'},403); return
            try:
                if self.path.startswith('/api/v2/'):
                    self.send(workspace_v2.post(self.path,payload,user)); return
                if self.path not in ('/api/logout','/api/password','/api/users'):
                    self.send({'error':'旧版记录只读，请从0.2品牌工作区开始研究'},403); return
                with mutation_lock:
                    if self.path=='/api/logout':
                        auth.logout(self.token()); self.send({'ok':True},cookie=self.cookie(clear=True)); return
                    if self.path=='/api/password':
                        if not auth.change_password(user['username'],payload.get('current',''),payload.get('password','')): raise ValueError('当前密码不正确')
                        self.send({'ok':True},cookie=self.cookie(clear=True)); return
                    if self.path=='/api/users':
                        if user['role']!='admin': self.send({'error':'仅管理员可添加账号'},403); return
                        self.send(auth.create_user(payload.get('username',''),payload.get('password',''),payload.get('role','editor'))); return
                    if self.path=='/api/profile': self.send(workspace.save_profile(payload)); return
                    if self.path=='/api/plan': self.send(workspace.create_plan(payload['profile_id'],payload.get('mode','live'))); return
                    if self.path=='/api/confirm': self.send(workspace.confirm_plan(payload['id'],payload['checksum'],user['username'])); return
                    if self.path=='/api/execute': self.send(workspace.execute_plan(payload['id'])); return
                    if self.path=='/api/revise': self.send(workspace.revise(payload['id'],payload['cards'],payload['checksum'],user['username'],payload.get('summary'))); return
                    if self.path=='/api/review': self.send(workspace.review(payload['id'],payload['decision'],user['username'],payload.get('note',''),payload['checksum'])); return
                    self.send({'error':'没有此操作'},404)
            except AuthorizationError as error: self.send({'error':str(error)},403)
            except PermissionError: self.send({'error':'无权执行该品牌操作'},403)
            except ValueError as error: self.send({'error':user_error(error)},400)
            except KeyError: self.send({'error':'缺少必要内容，请重新打开这条记录。'},400)
            except Exception: self.send({'error':'连接暂时未完成，你的内容已保留。请先查看对话记录。'},400)

    local=ThreadingHTTPServer((host,port),Handler)
    if lan:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(os.environ['SIGNAL_DESK_TLS_CERT'],os.environ['SIGNAL_DESK_TLS_KEY'])
        remote=ThreadingHTTPServer((lan,tls_port),Handler)
        remote.socket=context.wrap_socket(remote.socket,server_side=True,do_handshake_on_connect=False)
        threading.Thread(target=remote.serve_forever,daemon=True).start()
    print('Signal Desk authenticated team service started',flush=True)
    local.serve_forever()
def user_error(error):
    """Explain known input problems without reflecting provider/user secrets."""
    detail = str(error)
    messages = {
        '续期截止日期必须': '请填写有效的续期截止日期。',
        '管理员续期截止日期已经': '允许续期的截止日期已经过去。',
        '额度必须': '月度额度必须是非负有限金额。',
        '必须明确选择': '请明确选择付费方式和续期方式。',
        '只有明确启用的定时': '跨月续期只适用于定时研究。',
        '不付费执行无需': '不付费执行无需付费续期。',
        '正在处理上一条消息': '正在处理上一条消息，收到回复后再继续。',
        '该规划已提交或曾中断': '这条消息已处理或曾中断，记录已保留。请先查看对话，不要重复发送。',
        '同一规划请求编号': '这条消息的内容已变化，请作为新消息发送。',
        '继续对话时': '请在原对话中补充想法；另一个问题可以新建对话。',
        '查询数量': '方案提出的搜索范围超出本轮设置，请减少搜索组数或调整上限。',
        '研究预算': '研究深度超出允许范围，请在方案设置中调整。',
        '样本预算': '样本上限不足以覆盖搜索范围，请在方案设置中调整。',
        '日期必须': '请检查开始和结束日期。',
        '研究时间窗': '请检查时间范围，结束日期应晚于开始日期，且最多一年。',
        '方案还需要调整': '方案还需要调整，请先补充回答或修改设置。',
        '计划已变化': '方案已更新，请查看最新方案后再开始。',
        '稿件已变化': '稿件已更新，请重新打开后再修改。',
        'AI尚未配置': '对话助手暂未连接，请联系管理员检查设置。',
        '规划模型': '助手未能整理出有效方案。你的内容已保留，请检查设置后再继续。',
        '请补充必填': '请先写下想了解的问题。',
        '记录不存在': '找不到这条记录，请从任务列表重新打开。',
        '记录编号': '这条记录的地址无效，请从任务列表重新打开。',
        '研究方案已变化': '研究方案已更新，请检查当前方案后重新启用自动执行。',
        '研究方案已有新版本': '研究方案已有新版本，请刷新并确认最新方案。',
        '正在修改研究方案': '正在修改研究方案，请等回复后确认最新方案。',
        '上次研究方案修改未完成': '上次研究方案修改未完成，请核对并重新生成方案后确认。',
        '上一轮仍在执行': '上一轮研究仍在执行，请从执行记录查看进度。',
        '研究方案还需要调整': '请先完成研究方案，再启用自动执行。',
        '自动执行候选已变化': '时间设置已更新，请重新查看并确认。',
        '执行时间已经过去': '执行时间已经过去，请选择未来的日期和时间。',
        '执行时间请使用': '请填写有效时间，例如09:00。',
        '一次执行请设置': '请为这次执行选择具体日期。',
        '每周执行请设置': '请为每周执行选择星期。',
        '请选择一次': '请选择一次、每天或每周执行。',
        '请选择受支持的研究时间范围': '请选择要观察的日期范围。',
        '自动执行必须绑定': '请在当前任务中选择研究方案。',
        '任务名称': '请填写不超过150字的任务名称。',
    }
    return next((message for prefix, message in messages.items() if detail.startswith(prefix)),
                '这次操作未完成，请检查输入或重新打开记录。')
