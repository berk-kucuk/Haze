"""
HTTP + WebSocket bridge that lets Tor Browser users join a Haze chat session.

Virtual port mapping:
  .onion:80   → this HTTP server  (web browsers)
  .onion:5222 → ChatServer TCP    (native Haze clients)

Web clients speak a simple JSON WebSocket protocol. Events are bridged
to/from native TCP clients transparently.

Extra HTTP routes:
  GET  /logo.png   — the Haze wordmark used by the page
  POST /api/renew  — rotate Tor circuits (NEWNYM) without dropping sessions
"""

import asyncio
import hashlib
import hmac
import json
import uuid as _uuid
from pathlib import Path
from typing import Callable

from aiohttp import web, WSMsgType

from ..crypto import webe2e
from . import protocol as proto
from .server import ChatServer

# The page is a real file rather than a string literal because the Android
# client serves the very same bytes from its assets/web/ directory. Keeping one
# canonical copy is the only way two implementations of the same chat stay
# looking like one product.
_WEB_DIR = Path(__file__).resolve().parent.parent / "assets" / "web"
_INDEX_FILE = _WEB_DIR / "index.html"
_LOGO_FILE = _WEB_DIR / "logo.png"


def _hash_password(password: str) -> str:
    if not password:
        return ""
    return hashlib.sha256(b"haze-session-v1:" + password.encode()).hexdigest()

_ALLOWED_NICK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

_FILE_FRAMES = frozenset({"file_start", "file_chunk", "file_end"})
# Concurrent uploads one browser may have open. Each costs the receiving clients
# a reassembly buffer, so a browser must not be able to open hundreds.
_MAX_UPLOADS_IN_FLIGHT = 4
# base64 of one CHUNK_SIZE block, plus slack for padding/whitespace.
_MAX_CHUNK_B64 = (proto.CHUNK_SIZE * 4) // 3 + 1024

def _read_page() -> str:
    """Load the chat page. Read once at import; it never changes at runtime."""
    try:
        return _INDEX_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        # Serving a broken page would look like a Tor failure to the guest, so
        # say plainly what went wrong instead.
        return (
            "<!DOCTYPE html><meta charset='utf-8'>"
            "<body style='background:#080808;color:#d4d4d4;font-family:system-ui;"
            "padding:40px'><h1>Haze</h1><p>The web chat page is missing from this "
            f"installation.</p><p style='color:#666;font-size:12px'>{exc}</p></body>"
        )


_HTML = _read_page()


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
        app.router.add_get("/logo.png", self._handle_logo)
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

    async def _handle_logo(self, request: web.Request) -> web.Response:
        """The wordmark shown on the join card and in the top bar.

        A separate route rather than a data: URI so it is fetched once and
        cached, instead of inflating every page load over a Tor circuit.
        """
        try:
            body = _LOGO_FILE.read_bytes()
        except OSError:
            raise web.HTTPNotFound()
        return web.Response(
            body=body,
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

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
        # Set once the browser has completed the key exchange. Until then the
        # only frame accepted is "hello"; afterwards every frame in both
        # directions is an "encrypted" envelope.
        traffic_key: bytes | None = None
        # file_id → running totals for this connection's in-flight uploads.
        uploads: dict[str, dict] = {}

        async def send(payload: dict) -> None:
            await ws.send_json(webe2e.encrypt(traffic_key, payload))

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    mtype = data.get("type")

                    if mtype == "hello" and traffic_key is None:
                        # Key exchange first, so the nickname and the session
                        # password below never cross the socket in the clear.
                        try:
                            key = self._chat_server.web_traffic_key()
                            welcome = webe2e.wrap_traffic_key(
                                str(data.get("pubkey", "")),
                                str(data.get("alg", "")),
                                key,
                            )
                        except webe2e.WebCryptoError:
                            await ws.close()
                            return ws
                        traffic_key = key
                        await ws.send_json({"type": "welcome", **welcome})
                        continue

                    if traffic_key is None:
                        # Anything before the handshake is not part of the
                        # protocol; drop the connection rather than guess.
                        await ws.close()
                        return ws

                    if mtype != "encrypted":
                        continue
                    try:
                        data = webe2e.decrypt(traffic_key, data)
                    except webe2e.WebCryptoError:
                        await ws.close()
                        return ws
                    mtype = data.get("type")

                    if mtype == "join" and nick is None:
                        # Password check before admitting
                        if self._session_password_hash:
                            # Same brake as the native path (shared state).
                            throttle = self._chat_server._pw_throttle
                            if throttle.locked():
                                await send({"type": "auth_failed"})
                                await ws.close()
                                return ws
                            await asyncio.sleep(throttle.delay())
                            if not hmac.compare_digest(
                                str(data.get("password_hash", "")),
                                self._session_password_hash,
                            ):
                                throttle.failed()
                                await send({"type": "auth_failed"})
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
                        await send({"type": "userlist", "users": users})

                        # Notify Qt + TCP clients about the new participant
                        join_ev = {"type": "join", "nick": nick}
                        self._qt_callback(join_ev)
                        await self._chat_server._broadcast(join_ev)
                        await self._broadcast_web(join_ev, exclude=nick)

                    elif mtype == "chat" and nick is not None:
                        content = str(data.get("content", ""))[:4000]
                        msg_id = str(data.get("msg_id") or _uuid.uuid4())
                        # Reply metadata is quoted back to everyone, so it is
                        # length-capped like the message body. The nick is only
                        # ever displayed as text by every client.
                        reply_nick = data.get("reply_to_nick")
                        reply_content = data.get("reply_to_content")
                        await self._chat_server.receive_web_chat(
                            nick, content, msg_id,
                            reply_to_nick=str(reply_nick)[:20] if reply_nick else None,
                            reply_to_content=str(reply_content)[:200] if reply_content else None,
                        )

                    elif mtype == "typing" and nick is not None:
                        await self._chat_server.receive_web_typing(nick, bool(data.get("state")))

                    elif mtype in _FILE_FRAMES and nick is not None:
                        if not await self._handle_web_file(nick, mtype, data, uploads):
                            continue

                    elif mtype == "edit" and nick is not None:
                        # Offered by the browser UI only on the guest's own
                        # messages; the nick is stamped here either way, exactly
                        # as it is for a native client's edit.
                        msg_id = str(data.get("msg_id", ""))[:64]
                        content = str(data.get("content", ""))[:4000]
                        if msg_id and content:
                            await self._chat_server.receive_web_edit(nick, msg_id, content)

                    elif mtype == "delete" and nick is not None:
                        # The browser UI only offers this on the guest's own
                        # messages. The event is stamped with the authenticated
                        # nick server-side, exactly as a native client's delete
                        # is, so this grants a web guest nothing extra.
                        msg_id = str(data.get("msg_id", ""))[:64]
                        if msg_id:
                            await self._chat_server.receive_web_delete(nick, msg_id)

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
    # Uploads from browser clients
    # ------------------------------------------------------------------

    async def _handle_web_file(
        self, nick: str, mtype: str, data: dict, uploads: dict[str, dict]
    ) -> bool:
        """Validate and relay one file frame from a browser.

        Every limit is enforced by counting what actually arrives rather than
        trusting the sender's header — the same lesson as the receive path in
        the desktop UI, where a declared one-chunk file could be followed by
        unlimited chunks.
        """
        file_id = str(data.get("file_id", ""))[:64]
        if not file_id:
            return False

        if mtype == "file_start":
            if len(uploads) >= _MAX_UPLOADS_IN_FLIGHT:
                return False
            try:
                total_size = int(data.get("total_size", 0))
                total_chunks = int(data.get("total_chunks", 0))
            except (TypeError, ValueError):
                return False
            if not (0 < total_chunks <= proto.MAX_FILE_CHUNKS):
                return False
            if not (0 < total_size <= proto.MAX_FILE_BYTES):
                return False
            # A filename is displayed and offered as a download by every client;
            # strip anything that could escape a directory when saved.
            filename = str(data.get("filename", "file"))[:120]
            filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file"
            payload = proto.make_file_start(
                nick, file_id, filename,
                str(data.get("mime", "application/octet-stream"))[:100],
                total_size, total_chunks,
            )
            uploads[file_id] = {"bytes": 0, "chunks": total_chunks, "seen": set()}
            await self._chat_server.receive_web_file(nick, payload)
            return True

        upload = uploads.get(file_id)
        if upload is None:
            return False

        if mtype == "file_chunk":
            try:
                index = int(data.get("chunk_index"))
            except (TypeError, ValueError):
                return False
            if index < 0 or index >= upload["chunks"] or index in upload["seen"]:
                return False
            chunk = data.get("data", "")
            if not isinstance(chunk, str) or len(chunk) > _MAX_CHUNK_B64:
                return False
            upload["bytes"] += (len(chunk) * 3) // 4
            if upload["bytes"] > proto.MAX_FILE_BYTES:
                uploads.pop(file_id, None)
                return False
            upload["seen"].add(index)
            await self._chat_server.receive_web_file(
                nick, proto.make_file_chunk(nick, file_id, index, chunk)
            )
            return True

        # file_end
        uploads.pop(file_id, None)
        await self._chat_server.receive_web_file(nick, proto.make_file_end(nick, file_id))
        return True

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------

    async def broadcast_event(self, payload: dict) -> None:
        """Forward an event from the TCP/host path to all connected web clients."""
        await self._broadcast_web(payload)

    async def _broadcast_web(self, payload: dict, exclude: str | None = None) -> None:
        if not self._ws_clients:
            return
        # Browser clients share one traffic key, so the envelope is built once
        # and the same ciphertext goes to every one of them.
        try:
            envelope = webe2e.encrypt(self._chat_server.web_traffic_key(), payload)
        except Exception:
            return
        dead = []
        for nick, ws in list(self._ws_clients.items()):
            if nick == exclude:
                continue
            try:
                await ws.send_json(envelope)
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
