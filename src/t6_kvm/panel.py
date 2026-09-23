"""LAN-only authenticated KVM administration panel."""
import asyncio, base64, json, os, re, shutil, tempfile, time
from pathlib import Path
import aiohttp
from aiohttp import web
from kvmd.crypto import KvmdHtpasswdFile

CONFIG=Path('/etc/t6-kvm')
BACKUPS=Path('/root/agent.backup')
LOCK=asyncio.Lock()
TASKS=set()

def settings():
    p=CONFIG/'panel.json'
    return json.loads(p.read_text()) if p.exists() else {'continuous':False}

def atomic(path,data,mode=None):
    st=path.stat() if path.exists() else None
    fd,name=tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd,mode or (st.st_mode & 0o777 if st else 0o640))
        if st:os.fchown(fd,st.st_uid,st.st_gid)
        with os.fdopen(fd,'w') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

async def command(*args):
    p=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    out,err=await p.communicate()
    if p.returncode:raise RuntimeError(err.decode()[:300])
    return out.decode()

@web.middleware
async def auth(request,handler):
    try:
        kind,value=request.headers.get('Authorization','').split(' ',1)
        if kind.lower()!='basic':raise ValueError()
        user,password=base64.b64decode(value,validate=True).decode().split(':',1)
        valid=await asyncio.to_thread(KvmdHtpasswdFile(str(CONFIG/'htpasswd')).check_password,user,password)
        if not valid:raise ValueError()
    except (ValueError,UnicodeError):
        return web.Response(status=401,headers={'WWW-Authenticate':'Basic realm="T6 KVM"'},text='请使用 KVM 账户登录')
    request['user']=user
    if request.method=='POST':
        if request.headers.get('X-T6-Panel')!='1':raise web.HTTPForbidden()
        origin=request.headers.get('Origin')
        if origin and origin != request.scheme+'://'+request.host:raise web.HTTPForbidden()
    return await handler(request)

async def index(request):
    return web.Response(text=HTML,content_type='text/html',headers={'Cache-Control':'no-store'})

async def status(request):
    async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path='/run/t6-kvm/streamer.sock')) as session:
        try:
            async with session.get('http://localhost/state',timeout=aiohttp.ClientTimeout(total=2)) as r:video=(await r.json())['result']
        except (OSError,aiohttp.ClientError,TimeoutError):video={}
    ss=await command('ss','-tin','( sport = :5900 )')
    clients=[]
    for line in ss.splitlines():
        if line.startswith('ESTAB'):
            cols=line.split();clients.append({'peer':cols[4],'send_queue':int(cols[2]),'rtt_ms':None})
        elif clients:
            m=re.search(r' rtt:([0-9.]+)',line)
            if m:clients[-1]['rtt_ms']=float(m.group(1))
    toml=(CONFIG/'streamer.toml').read_text()
    bitrate=int(re.search(r'^bitrate_kbps[ ]*=[ ]*([0-9]+)',toml,re.M)[1])
    journal=await command('journalctl','-u','t6-kvmd-vnc','-n','80','--no-pager','-o','cat')
    selected=[l.split('Using preferred ',1)[1] for l in journal.splitlines() if 'Using preferred ' in l]
    return web.json_response({'video':video,'clients':clients,'user':request['user'],'settings':settings(),
        'bitrate_kbps':bitrate,'encoding':selected[-1] if selected and clients else '无活动会话',
        'device':'NanoPC-T6 · HDMI IN / USB HID','ip':'192.168.123.99',
        'reconfiguring':bool(TASKS),'end_to_end_latency_ms':None},headers={'Cache-Control':'no-store'})

async def restart(main):
    await asyncio.sleep(.6)
    await command('systemctl','restart',*(['t6-kvmd','t6-kvmd-vnc'] if main else ['t6-kvmd-vnc']))

async def update(request):
    async with LOCK:
        if TASKS:return web.json_response({'error':'正在应用上一项设置，请稍后重试'},status=409)
        d=await request.json()
        try:
            bitrate=d['bitrate_kbps'];continuous=d['continuous'];user=d['username'];password=d.get('password','')
            if type(bitrate)!=int or not 100<=bitrate<=20000:raise ValueError('码率须为 100–20000 kbps')
            if type(continuous)!=bool:raise ValueError('无效的发帧模式')
            if not isinstance(user,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,32}',user):raise ValueError('账户名仅支持字母、数字、下划线和短横线')
            if not isinstance(password,str) or len(password)>8 or any(ord(c)<33 or ord(c)>126 for c in password):raise ValueError('兼容 VNC 密码需为 1–8 个可见 ASCII 字符；留空保留')
            if user!=request['user'] and not password:raise ValueError('修改账户名时请同时填写新密码')
        except (KeyError,ValueError) as e:return web.json_response({'error':str(e)},status=400)
        toml=CONFIG/'streamer.toml';old=toml.read_text();new=re.sub(r'(?m)^bitrate_kbps[ ]*=[ ]*[0-9]+',f'bitrate_kbps = {bitrate}',old)
        main=old!=new
        # Backups are confined to this panel and retain the newest two snapshots.
        root=BACKUPS;root.mkdir(exist_ok=True,mode=0o700)
        backup=root/('t6-panel-'+str(time.time_ns()));backup.mkdir(mode=0o700)
        for name in ['streamer.toml','main.yaml','htpasswd','vncpasswd','panel.json']:
            if (CONFIG/name).exists():shutil.copy2(CONFIG/name,backup/name)
        (backup/'owner').write_text('t6-panel-v1')
        backups=sorted(p for p in root.glob('t6-panel-*') if (p/'owner').is_file() and (p/'owner').read_text()=='t6-panel-v1')
        for p in backups[:-2]:shutil.rmtree(p)
        atomic(toml,new)
        # kvmd's configured initial bitrate must agree with the worker config.
        p=CONFIG/'main.yaml';yaml=p.read_text();yaml=re.sub(r'(h264_bitrate: [{]default: )[0-9]+',lambda m:m[1]+str(bitrate),yaml);atomic(p,yaml)
        atomic(CONFIG/'panel.json',json.dumps({'continuous':continuous}))
        if password:
            h=KvmdHtpasswdFile(str(CONFIG/'htpasswd'))
            if user!=request['user']:h.delete(request['user'])
            h.set_password(user,password);h.save()
            atomic(CONFIG/'vncpasswd',password+chr(10))
        task=asyncio.create_task(restart(main));TASKS.add(task)
        def done(t):
            TASKS.discard(t)
            if not t.cancelled() and t.exception():print('Panel apply failed:',type(t.exception()).__name__,flush=True)
        task.add_done_callback(done)
        return web.json_response({'ok':True,'message':'设置已保存，服务正在应用。VNC 需重新连接；修改账户后请刷新面板并使用新账户登录。'})

HTML='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T6 KVM 控制面板</title>
<style>body{margin:0;background:#101827;color:#e8eef8;font:16px system-ui}main{max-width:1000px;margin:40px auto;padding:24px}h1{font-size:30px}small,.muted{color:#9bafc9}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}.card,form{background:#1b283b;border:1px solid #33455c;border-radius:14px;padding:22px;margin:15px 0}.value{font-size:23px;margin-top:12px;overflow-wrap:anywhere}label{display:block;margin:18px 0 6px}input,select,button{box-sizing:border-box;width:100%;padding:12px;border-radius:8px;border:1px solid #52677e;background:#101827;color:white;font:inherit}button{background:#287eaa;cursor:pointer;margin-top:22px}button:disabled{opacity:.5}#msg{white-space:pre-wrap;padding:12px}table{width:100%;text-align:left}td,th{padding:10px;border-bottom:1px solid #33455c}</style>
<main><small>HDMI · USB HID · VNC</small><h1>T6 KVM 控制面板</h1><p id="health">正在读取状态…</p>
<div class="grid"><div class="card">连接设备<div class="value" id="device">—</div><small id="ip"></small></div><div class="card">视频输入<div class="value" id="resolution">—</div><small id="fps"></small></div><div class="card">当前编码<div class="value" id="encoding">—</div></div><div class="card">发帧模式<div class="value" id="mode">—</div><small id="rate"></small></div></div>
<div class="card"><h3>VNC 连接与延迟</h3><table><thead><tr><th>客户端 IP / 端口</th><th>网络 RTT</th><th>发送队列</th></tr></thead><tbody id="clients"></tbody></table><p class="muted">RTT 是 TCP 往返时间，不是完整操作延迟。端到端延迟暂无实时测量。被控 PC 的 IP 无法从 HDMI / USB 自动获取。</p></div>
<form id="form"><h3>服务设置</h3><label>H.264 目标码率（kbps）</label><input id="bitrate" type="number" min="100" max="20000" required><small>范围 100–20000。JPEG 兼容模式使用质量 70、最高 15 fps，不受此码率控制。</small><label>发帧模式</label><select id="continuous"><option value="false">按需：客户端请求后发送</option><option value="true">连续：支持的客户端可启用 ContinuousUpdates</option></select><label>账户名</label><input id="username" autocomplete="username" pattern="[a-zA-Z0-9_-]{1,32}" required><label>新密码（留空保留）</label><input id="password" type="password" autocomplete="new-password" maxlength="8"><small>兼容 Jump Desktop 的标准 VNC 认证，仅使用密码；最多 8 个可见 ASCII 字符。面板和 Plain 登录同时使用账户名。</small><p>保存会短暂重启相关服务并断开 VNC。面板使用当前 KVM 账户登录。</p><button id="save">保存并应用</button><div id="msg" role="status"></div></form><small>状态每 3 秒更新 · 局域网 HTTP</small></main>
<script>
const $=id=>document.getElementById(id);let initialized=false;
async function poll(){try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('请刷新页面并使用当前账户登录');let s=await r.json(),t=s.video.t6||{},i=t.input||{};$('health').textContent=s.reconfiguring?'正在应用设置…':t.online?'视频在线':'视频暂不可用';$('device').textContent=s.device;$('ip').textContent=s.ip+':5900';$('resolution').textContent=i.width?i.width+' × '+i.height:'无信号';$('fps').textContent='实际编码 '+(t.encoded_fps_observed||0)+' fps';$('encoding').textContent=s.encoding;$('mode').textContent=s.settings.continuous?'连续（需客户端支持）':'按需';$('rate').textContent='H.264 目标 '+s.bitrate_kbps+' kbps';$('clients').replaceChildren();for(let c of s.clients){let tr=document.createElement('tr');for(let value of [c.peer,c.rtt_ms===null?'—':c.rtt_ms+' ms',c.send_queue+' B']){let td=document.createElement('td');td.textContent=value;tr.append(td)}$('clients').append(tr)}if(!s.clients.length){let tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=3;td.textContent='当前没有 VNC 连接';tr.append(td);$('clients').append(tr)}if(!initialized){$('bitrate').value=s.bitrate_kbps;$('continuous').value=String(s.settings.continuous);$('username').value=s.user;initialized=true}}catch(e){$('health').textContent=e.message}}
$('form').onsubmit=async e=>{e.preventDefault();$('save').disabled=true;try{let r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json','X-T6-Panel':'1'},body:JSON.stringify({bitrate_kbps:Number($('bitrate').value),continuous:$('continuous').value==='true',username:$('username').value,password:$('password').value})});let d=await r.json();if(!r.ok)throw Error(d.error||'保存失败');$('msg').textContent=d.message;$('password').value=''}catch(e){$('msg').textContent=e.message}finally{setTimeout(()=>{$('save').disabled=false;poll()},2000)}};poll();setInterval(poll,3000);
</script></html>'''

def main():
    app=web.Application(middlewares=[auth],client_max_size=4096)
    app.router.add_get('/',index);app.router.add_get('/api/status',status);app.router.add_post('/api/settings',update)
    web.run_app(app,host='192.168.123.99',port=5899,access_log=None)
if __name__=='__main__':main()
