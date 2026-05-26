"""
HTTP + WebSocket bridge that lets Tor Browser users join a Haze chat session.

Virtual port mapping:
  .onion:80   → this HTTP server  (web browsers)
  .onion:5222 → ChatServer TCP    (native Haze clients)

Web clients speak a simple JSON WebSocket protocol. Events are bridged
to/from native TCP clients transparently.

Extra HTTP routes:
  POST /api/renew  — rotate Tor circuits (NEWNYM) without dropping sessions
"""

import asyncio
import hashlib
import json
import uuid as _uuid
from typing import Callable

from aiohttp import web, WSMsgType

from .server import ChatServer


def _hash_password(password: str) -> str:
    if not password:
        return ""
    return hashlib.sha256(b"haze-session-v1:" + password.encode()).hexdigest()

_ALLOWED_NICK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Haze · Secure Chat</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080808;--surface:#0f0f0f;--surface2:#141414;--surface3:#1a1a1a;
  --border:#1e1e1e;--border2:#252525;--text:#d4d4d4;--text2:#909090;
  --text3:#484848;--text4:#2c2c2c;--accent:#ffffff;--green:#34c759;
  --red:#ff3b30;--yellow:#ffd60a;--radius:12px;--radius-sm:8px;
}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--text);font-family:"SF Pro Text","Segoe UI",system-ui,sans-serif;font-size:14px;display:flex;flex-direction:column}

/* ── Install banner ── */
#install-banner{
  background:linear-gradient(90deg,rgba(52,199,89,.12),rgba(52,199,89,.06));
  border-bottom:1px solid rgba(52,199,89,.18);
  padding:9px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0;
  font-size:12px;
}
#install-banner .ib-icon{color:var(--green);font-size:14px;flex-shrink:0}
#install-banner .ib-text{flex:1;color:var(--text2)}
#install-banner .ib-text strong{color:var(--text);font-weight:600}
#install-banner .ib-link{
  background:var(--green);color:#000;font-size:11px;font-weight:700;
  padding:5px 12px;border-radius:20px;text-decoration:none;flex-shrink:0;
  letter-spacing:.3px;transition:opacity .15s;
}
#install-banner .ib-link:hover{opacity:.85}
#install-banner .ib-dismiss{
  background:none;border:none;color:var(--text3);cursor:pointer;
  font-size:14px;padding:2px 4px;flex-shrink:0;transition:color .15s;
}
#install-banner .ib-dismiss:hover{color:var(--text2)}

/* ── Join screen ── */
#js{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  flex:1;gap:0;padding:32px 24px;
}
.js-card{
  background:var(--surface);border:1px solid var(--border2);
  border-radius:20px;padding:36px 32px;width:100%;max-width:360px;
  display:flex;flex-direction:column;gap:18px;
}
.js-logo{text-align:center;margin-bottom:4px}
.js-logo h1{font-size:28px;font-weight:200;letter-spacing:10px;color:var(--accent)}
.js-logo p{font-size:10px;color:var(--text4);letter-spacing:2px;margin-top:6px}
.js-enc{
  display:flex;align-items:center;gap:8px;background:rgba(52,199,89,.08);
  border:1px solid rgba(52,199,89,.15);border-radius:var(--radius-sm);
  padding:9px 12px;
}
.js-enc .enc-dot{width:7px;height:7px;border-radius:50%;background:var(--green);flex-shrink:0}
.js-enc .enc-text{font-size:11px;color:var(--green);font-weight:600;letter-spacing:.5px}
.js-enc .enc-note{font-size:10px;color:var(--text3);margin-left:auto}
.js-sep{height:1px;background:var(--border);margin:2px 0}
input[type=text],input[type=password]{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:var(--radius-sm);color:var(--text);font-size:14px;
  padding:13px 16px;width:100%;outline:none;font-family:inherit;
  transition:border-color .15s;
}
input[type=text]:focus,input[type=password]:focus{border-color:var(--border2)}
button{font-family:inherit;cursor:pointer;border:none;border-radius:var(--radius-sm)}
#jb{
  background:var(--accent);color:#000;font-size:14px;font-weight:600;
  padding:14px 0;width:100%;border-radius:var(--radius-sm);transition:opacity .15s;
}
#jb:hover{opacity:.9}
#jb:disabled{opacity:.4}
#je{color:var(--red);font-size:11px;min-height:16px;text-align:center}
.js-web-note{
  font-size:10px;color:var(--text4);text-align:center;line-height:1.6;
  padding:0 8px;
}
.js-web-note a{color:var(--text3);text-decoration:none}
.js-web-note a:hover{color:var(--text2)}

/* ── Chat layout ── */
#cs{display:none;flex-direction:column;flex:1;overflow:hidden}
/* top bar */
#topbar{
  height:46px;background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 16px;gap:12px;flex-shrink:0;
}
#topbar .tb-brand{font-size:13px;font-weight:700;letter-spacing:4px;color:var(--accent);margin-right:4px}
#topbar .tb-enc{
  display:flex;align-items:center;gap:5px;background:rgba(52,199,89,.08);
  border:1px solid rgba(52,199,89,.14);border-radius:20px;
  padding:4px 10px;font-size:10px;color:var(--green);font-weight:600;letter-spacing:.5px;
}
#topbar .tb-enc-dot{width:5px;height:5px;border-radius:50%;background:var(--green)}
#topbar .tb-sep{flex:1}
#renew-btn{
  background:var(--surface3);border:1px solid var(--border2);color:var(--text2);
  font-size:11px;font-weight:600;padding:6px 13px;border-radius:20px;
  display:flex;align-items:center;gap:5px;transition:all .15s;letter-spacing:.3px;
}
#renew-btn:hover{background:rgba(255,255,255,.06);border-color:var(--border);color:var(--text)}
#renew-btn:disabled{opacity:.4}
#renew-btn .rn-icon{font-size:13px;transition:transform .4s}
#renew-btn.spinning .rn-icon{transform:rotate(360deg)}
#renew-status{font-size:10px;color:var(--text3);white-space:nowrap}
/* chat body */
#chat-body{display:flex;flex:1;overflow:hidden}
/* sidebar */
#sb{
  width:180px;background:var(--surface);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;
}
#sbt{padding:14px 14px 8px;font-size:9px;color:var(--text4);letter-spacing:2px;text-transform:uppercase}
#ul{list-style:none;flex:1;overflow-y:auto;padding:0 8px 8px}
#ul li{
  padding:7px 10px;font-size:12px;color:var(--text3);border-radius:var(--radius-sm);
  margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  display:flex;align-items:center;gap:7px;
}
#ul li::before{content:'';width:6px;height:6px;border-radius:50%;background:#333;flex-shrink:0}
#ul li.me{color:var(--text2)}
#ul li.me::before{background:var(--green)}
/* main */
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#msgs{flex:1;overflow-y:auto;padding:16px 20px 4px;display:flex;flex-direction:column;gap:3px}
.mr{display:flex;flex-direction:column;max-width:72%}
.mr.me{align-self:flex-end;align-items:flex-end}
.mr.ot{align-self:flex-start;align-items:flex-start}
.mn{font-size:10px;color:var(--text4);margin-bottom:3px;padding:0 4px;letter-spacing:.3px;font-weight:600;text-transform:uppercase}
.mr.me .mn{color:#3a3a3a}
.bbl{
  border-radius:var(--radius);padding:9px 13px;font-size:13px;
  word-break:break-word;line-height:1.55;
}
.mr.ot .bbl{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.05);color:#cccccc}
.mr.me .bbl{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.07);color:var(--text)}
.sm{
  font-size:10px;color:var(--text4);text-align:center;padding:6px 0;
  align-self:center;letter-spacing:.5px;
}
#tb{height:20px;padding:0 20px;font-size:11px;color:var(--text4);font-style:italic;flex-shrink:0}
/* input */
#ib{
  background:rgba(8,8,8,.97);border-top:1px solid var(--border);
  padding:10px 14px;display:flex;gap:10px;align-items:flex-end;flex-shrink:0;
}
#mi{
  flex:1;background:rgba(255,255,255,.04);border:1px solid var(--border);
  border-radius:var(--radius);color:var(--text);font-size:14px;
  padding:10px 14px;outline:none;resize:none;font-family:inherit;
  line-height:1.4;max-height:120px;overflow-y:auto;transition:border-color .15s;
}
#mi:focus{border-color:var(--border2)}
#sb2{
  background:var(--accent);color:#000;width:40px;height:40px;font-size:18px;
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
  border-radius:var(--radius-sm);transition:opacity .15s;
}
#sb2:hover{opacity:.9}
/* scrollbar */
::-webkit-scrollbar{width:3px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#1e1e1e;border-radius:2px}
</style>
</head>
<body>

<!-- ── Install / upgrade banner ── -->
<div id="install-banner">
  <span class="ib-icon">⬡</span>
  <span class="ib-text">
    <strong>Haze Native App</strong> — E2E encrypted with Tor. The native app provides stronger
    security guarantees and a better experience.
  </span>
  <a class="ib-link" href="https://haze.berkkucukk.com" target="_blank" rel="noopener">
    Get the App
  </a>
  <button class="ib-dismiss" id="ib-dismiss" title="Dismiss">✕</button>
</div>

<!-- ── Join screen ── -->
<div id="js">
  <div class="js-card">
    <div class="js-logo">
      <h1>HAZE</h1>
      <p>ANONYMOUS · ENCRYPTED · EPHEMERAL</p>
    </div>

    <div class="js-enc">
      <span class="enc-dot"></span>
      <span class="enc-text">END-TO-END ENCRYPTED</span>
      <span class="enc-note">Tor Hidden Service</span>
    </div>

    <div class="js-sep"></div>

    <input id="ni" type="text" placeholder="Nickname" maxlength="20"
           autocomplete="off" spellcheck="false">
    <input id="pw" type="password" placeholder="Session password (if required)"
           autocomplete="off">
    <button id="jb">Join Chat</button>
    <div id="je"></div>

    <p class="js-web-note">
      Web access is end-to-end encrypted via Tor.<br>
      For maximum security, use the
      <a href="https://haze.berkkucukk.com" target="_blank" rel="noopener">native Haze app</a>.
    </p>
  </div>
</div>

<!-- ── Chat screen ── -->
<div id="cs">
  <!-- Top bar -->
  <div id="topbar">
    <span class="tb-brand">HAZE</span>
    <div class="tb-enc">
      <span class="tb-enc-dot"></span>
      E2E ENCRYPTED · TOR
    </div>
    <span class="tb-sep"></span>
    <span id="renew-status"></span>
    <button id="renew-btn" title="Rotate Tor circuits without dropping your session">
      <span class="rn-icon">⟳</span> Renew Circuit
    </button>
  </div>

  <!-- Body -->
  <div id="chat-body">
    <!-- Sidebar -->
    <div id="sb">
      <div id="sbt">Participants</div>
      <ul id="ul"></ul>
    </div>

    <!-- Main area -->
    <div id="main">
      <div id="msgs"></div>
      <div id="tb"></div>
      <div id="ib">
        <textarea id="mi" placeholder="Message…" rows="1" maxlength="4000"></textarea>
        <button id="sb2">↑</button>
      </div>
    </div>
  </div>
</div>

<script>
"use strict";
let ws=null,myNick=null,tyTimer=null,isTy=false;
const sentIds=new Set();
const $=id=>document.getElementById(id);
const js=$("js"),cs=$("cs"),ni=$("ni"),pw=$("pw"),jb=$("jb"),je=$("je");
const msgs=$("msgs"),ul=$("ul"),mi=$("mi"),sb2=$("sb2"),tb=$("tb");
const renewBtn=$("renew-btn"),renewStatus=$("renew-status");

// ── Install banner ─────────────────────────────────────────────────
$("ib-dismiss").addEventListener("click",()=>{
  $("install-banner").style.display="none";
});

// ── Password hashing (matches server: SHA-256("haze-session-v1:" + pw)) ──
async function hashPassword(password){
  if(!password)return"";
  const enc=new TextEncoder();
  const prefix=enc.encode("haze-session-v1:");
  const pwBytes=enc.encode(password);
  const data=new Uint8Array(prefix.length+pwBytes.length);
  data.set(prefix,0);data.set(pwBytes,prefix.length);
  const hashBuf=await crypto.subtle.digest("SHA-256",data);
  return Array.from(new Uint8Array(hashBuf)).map(b=>b.toString(16).padStart(2,"0")).join("");
}

// ── Join ──────────────────────────────────────────────────────────
async function join(){
  const nick=ni.value.trim().replace(/[^a-zA-Z0-9_\-]/g,"").slice(0,20);
  if(!nick){je.textContent="Nickname: letters, numbers, _ or - only";return;}
  je.textContent="";jb.disabled=true;
  const passwordHash=await hashPassword(pw.value);
  const proto=location.protocol==="https:"?"wss":"ws";
  ws=new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen=()=>{ws.send(JSON.stringify({type:"join",nick,password_hash:passwordHash}));myNick=nick;};
  ws.onmessage=e=>handle(JSON.parse(e.data));
  ws.onclose=()=>{sysMsg("Disconnected.");mi.disabled=true;sb2.disabled=true;renewBtn.disabled=true;};
  ws.onerror=()=>{je.textContent="Connection failed. Reload page.";jb.disabled=false;};
  js.style.display="none";cs.style.display="flex";
}

// ── Event handler ─────────────────────────────────────────────────
function handle(d){
  switch(d.type){
    case"userlist":ul.innerHTML="";d.users.forEach(addUser);break;
    case"join":sysMsg(d.nick+" joined");addUser(d.nick);break;
    case"leave":sysMsg(d.nick+" left");rmUser(d.nick);break;
    case"chat":
      clearTyFor(d.nick);
      if(d.msg_id&&sentIds.has(d.msg_id)){sentIds.delete(d.msg_id);break;}
      addMsg(d.nick,d.content,d.msg_id);break;
    case"typing":setTy(d.nick,d.state);break;
    case"delete":delMsg(d.msg_id);break;
    case"edit":editMsg(d.msg_id,d.content);break;
    case"panic":sysMsg("⚠ Session ended.");ws.close();break;
    case"kicked":sysMsg("You were removed.");ws.close();break;
    case"auth_failed":
      // Go back to join screen with error
      cs.style.display="none";js.style.display="flex";
      je.textContent="Wrong session password.";
      jb.disabled=false;ws=null;myNick=null;
      break;
  }
}

function addUser(n){
  if(ul.querySelector(`[data-n="${CSS.escape(n)}"]`))return;
  const li=document.createElement("li");
  li.dataset.n=n;li.textContent=n;
  if(n===myNick)li.className="me";
  ul.appendChild(li);
}
function rmUser(n){const el=ul.querySelector(`[data-n="${CSS.escape(n)}"]`);if(el)el.remove();}

function addMsg(nick,text,msgId){
  const me=nick===myNick;
  const row=document.createElement("div");
  row.className="mr "+(me?"me":"ot");
  if(msgId)row.dataset.mid=msgId;
  const mn=document.createElement("div");mn.className="mn";mn.textContent=nick;
  const bbl=document.createElement("div");bbl.className="bbl";bbl.textContent=text;
  row.appendChild(mn);row.appendChild(bbl);
  msgs.appendChild(row);msgs.scrollTop=msgs.scrollHeight;
}
function sysMsg(t){
  const el=document.createElement("div");el.className="sm";el.textContent=t;
  msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;
}

const tyNicks=new Set();
function setTy(nick,state){
  if(nick===myNick)return;
  state?tyNicks.add(nick):tyNicks.delete(nick);
  tb.textContent=tyNicks.size?[...tyNicks].join(", ")+" is typing…":"";
}
function clearTyFor(n){setTy(n,false);}

function delMsg(id){
  const r=msgs.querySelector(`[data-mid="${CSS.escape(id)}"]`);
  if(r){const b=r.querySelector(".bbl");if(b){b.style.opacity=".3";b.style.textDecoration="line-through";}}
}
function editMsg(id,text){
  const r=msgs.querySelector(`[data-mid="${CSS.escape(id)}"]`);
  if(r){const b=r.querySelector(".bbl");if(b)b.textContent=text+" (edited)";}
}

// ── Send message ──────────────────────────────────────────────────
function send(){
  const text=mi.value.trim();
  if(!text||!ws||ws.readyState!==1)return;
  const msgId=crypto.randomUUID();
  sentIds.add(msgId);
  ws.send(JSON.stringify({type:"chat",content:text,msg_id:msgId}));
  addMsg(myNick,text,msgId);
  mi.value="";mi.style.height="auto";stopTy();
}

function stopTy(){
  if(isTy){isTy=false;if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:"typing",state:false}));}
  clearTimeout(tyTimer);
}

mi.addEventListener("input",()=>{
  mi.style.height="auto";mi.style.height=Math.min(mi.scrollHeight,120)+"px";
  if(!isTy&&ws&&ws.readyState===1){isTy=true;ws.send(JSON.stringify({type:"typing",state:true}));}
  clearTimeout(tyTimer);tyTimer=setTimeout(stopTy,3000);
});
mi.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}});
sb2.addEventListener("click",send);
jb.addEventListener("click",join);
ni.addEventListener("keydown",e=>{if(e.key==="Enter")join();});

// ── Renew circuit ─────────────────────────────────────────────────
renewBtn.addEventListener("click",async()=>{
  renewBtn.disabled=true;
  renewBtn.classList.add("spinning");
  renewStatus.textContent="";
  try{
    const r=await fetch("/api/renew",{method:"POST"});
    if(r.ok){
      renewStatus.textContent="Circuit renewed";
      sysMsg("⟳ Tor circuit renewed — existing session preserved");
    }else{
      renewStatus.textContent="Failed";
    }
  }catch{
    renewStatus.textContent="Failed";
  }finally{
    setTimeout(()=>{
      renewBtn.disabled=false;
      renewBtn.classList.remove("spinning");
      setTimeout(()=>{renewStatus.textContent="";},3000);
    },1200);
  }
});
</script>
</body>
</html>
"""


class WebChatServer:
    """
    Bridges Tor Browser ↔ native Haze clients.

    - Serves the HTML chat UI on GET /
    - Accepts WebSocket connections on GET /ws
    - POST /api/renew  → rotate Tor circuits via renew_circuit_cb (NEWNYM)
    - Events from TCP/host path reach web clients via broadcast_event()
    - Messages from web clients are forwarded to ChatServer and Qt via
      ChatServer.receive_web_chat / receive_web_typing
    """

    def __init__(
        self,
        host_nick: str,
        http_port: int,
        chat_server: ChatServer,
        qt_callback: Callable[[dict], None],
        loop: asyncio.AbstractEventLoop,
        renew_circuit_cb: Callable[[], None] | None = None,
        session_password: str = "",
    ) -> None:
        self._host_nick = host_nick
        self._http_port = http_port
        self._chat_server = chat_server
        self._qt_callback = qt_callback
        self._loop = loop
        self._renew_circuit_cb = renew_circuit_cb
        self._session_password_hash = _hash_password(session_password)
        self._ws_clients: dict[str, web.WebSocketResponse] = {}
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_post("/api/renew", self._handle_renew)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self._http_port)
        await site.start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_HTML, content_type="text/html")

    async def _handle_renew(self, request: web.Request) -> web.Response:
        if self._renew_circuit_cb is None:
            return web.Response(status=503, text="Circuit renewal not available")
        try:
            self._renew_circuit_cb()
            return web.Response(text="ok")
        except Exception as exc:
            return web.Response(status=500, text=str(exc))

    # ------------------------------------------------------------------
    # WebSocket handler
    # ------------------------------------------------------------------

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        nick: str | None = None

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    mtype = data.get("type")

                    if mtype == "join" and nick is None:
                        # Password check before admitting
                        if self._session_password_hash:
                            if data.get("password_hash", "") != self._session_password_hash:
                                await ws.send_json({"type": "auth_failed"})
                                await ws.close()
                                return ws

                        nick = self._make_nick(data.get("nick", ""), prefix="[web]")
                        self._ws_clients[nick] = ws

                        # Send current user list to newcomer
                        users = (
                            [self._host_nick]
                            + list(self._chat_server._clients.keys())
                            + list(self._ws_clients.keys())
                        )
                        await ws.send_json({"type": "userlist", "users": users})

                        # Notify Qt + TCP clients about the new participant
                        join_ev = {"type": "join", "nick": nick}
                        self._qt_callback(join_ev)
                        await self._chat_server._broadcast(join_ev)
                        await self._broadcast_web(join_ev, exclude=nick)

                    elif mtype == "chat" and nick is not None:
                        content = str(data.get("content", ""))[:4000]
                        msg_id = str(data.get("msg_id") or _uuid.uuid4())
                        await self._chat_server.receive_web_chat(nick, content, msg_id)

                    elif mtype == "typing" and nick is not None:
                        await self._chat_server.receive_web_typing(nick, bool(data.get("state")))

                elif msg.type == WSMsgType.ERROR:
                    break

        finally:
            if nick and nick in self._ws_clients:
                del self._ws_clients[nick]
                leave_ev = {"type": "leave", "nick": nick}
                self._qt_callback(leave_ev)
                await self._chat_server._broadcast(leave_ev)
                await self._broadcast_web(leave_ev)

        return ws

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------

    async def broadcast_event(self, payload: dict) -> None:
        """Forward an event from the TCP/host path to all connected web clients."""
        await self._broadcast_web(payload)

    async def _broadcast_web(self, payload: dict, exclude: str | None = None) -> None:
        dead = []
        for nick, ws in list(self._ws_clients.items()):
            if nick == exclude:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(nick)
        for nick in dead:
            self._ws_clients.pop(nick, None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_nick(self, raw: str, prefix: str = "") -> str:
        sanitized = "".join(c for c in raw if c in _ALLOWED_NICK)[:20]
        base = prefix + (sanitized or "user")
        taken = set(self._ws_clients) | set(self._chat_server._clients) | {self._host_nick}
        nick, i = base, 2
        while nick in taken:
            nick = f"{base}_{i}"
            i += 1
        return nick
