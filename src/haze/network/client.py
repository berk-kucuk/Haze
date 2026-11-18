"""
Join-mode asyncio client. Connects to host via Tor SOCKS5.
"""

import asyncio
import base64
import itertools
import time
from typing import Callable

from python_socks.async_.asyncio import Proxy

from ..crypto import session_auth
from ..crypto.e2e import SessionCrypto
from . import protocol as proto
from ..logging_setup import get_logger, redact

log = get_logger("client")


# Initial-connect retry policy: a fresh onion descriptor can take a while to
# propagate, so the first attempt often fails even when the host is up.
_CONNECT_ATTEMPTS = 3
_CONNECT_RETRY_DELAY = 5  # seconds between attempts

# Outgoing send-queue priorities — lower sorts first (asyncio.PriorityQueue).
_PRIO_CONTROL = 0  # chat, typing, ping/pong, delete, edit, leave, panic
_PRIO_FILE = 1      # file_start / file_chunk / file_end

# Sentinel enqueued to make _writer_loop exit after flushing what's ahead of it.
_SHUTDOWN = object()


class ChatClient:
    def __init__(
        self,
        nick: str,
        onion_host: str,
        socks_port: int,
        on_event: Callable[[dict], None],
        session_password: str = "",
    ) -> None:
        self._nick = nick
        self._onion_host = onion_host.strip().rstrip("/")
        self._socks_port = socks_port
        self._on_event = on_event
        # Never the password, and no longer its v1 digest: a v2 proof is
        # computed per challenge (see crypto/session_auth.py). The key is
        # derived on first use and kept for reconnects.
        self._session_password = session_password
        self._auth_key: bytes | None = None

        self._crypto = SessionCrypto()
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

        # Outgoing frames are queued and sent by a single writer task, in
        # priority order — control frames (chat/typing/ping/…) always jump
        # ahead of any still-pending file/GIF chunks, so a large attachment
        # can never delay a normal message by more than one chunk's send
        # time. See _writer_loop / _enqueue.
        self._send_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._send_seq = itertools.count()
        self._writer_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        # A freshly published onion service often isn't reachable on the first
        # try — its descriptor may not have propagated through the Tor DHT yet.
        # Retry a few times before giving up so the user doesn't have to
        # manually reconnect. auth_failed is terminal and never retried.
        last_error: Exception | None = None
        # Redacted: the full onion address and nickname together are a record of
        # who this user talked to, and the log file outlives the session.
        log.info("connect() → %s (nick=%s)", redact(self._onion_host), redact(self._nick))
        for attempt in range(1, _CONNECT_ATTEMPTS + 1):
            try:
                log.info("connect attempt %d/%d", attempt, _CONNECT_ATTEMPTS)
                ok = await self._attempt_connect()
                if ok:
                    return          # connected, or auth_failed (terminal)
            except Exception as e:               # unreachable / timeout / reset
                last_error = e
                log.warning("connect attempt %d failed: %r", attempt, e)
            if attempt < _CONNECT_ATTEMPTS:
                await asyncio.sleep(_CONNECT_RETRY_DELAY)
        # All attempts failed → tell the UI instead of hanging on "connecting…".
        log.error("all %d connect attempts failed (last: %r)", _CONNECT_ATTEMPTS, last_error)
        self._on_event({"type": "disconnected"})
        if last_error is not None:
            return

    async def _attempt_connect(self) -> bool:
        """One connect + handshake attempt. Returns True on success or a terminal
        auth failure; raises on a retryable transport error."""
        proxy = Proxy.from_url(f"socks5://127.0.0.1:{self._socks_port}")
        sock = await proxy.connect(
            dest_host=self._onion_host,
            dest_port=5222,
            timeout=120,
        )
        reader, writer = await asyncio.open_connection(sock=sock)
        self._writer = writer

        await proto.send_msg(writer, {
            "type": "hello",
            "public_key": self._crypto.public_key_b64,
            "nick": self._nick,
            "auth": session_auth.VERSION,
        })

        log.info("SOCKS connected, hello sent; awaiting welcome")
        response = await asyncio.wait_for(proto.recv_msg(reader), timeout=60)
        if response.get("type") == "challenge":
            # The host wants the session password. Without one there is
            # nothing to prove; with one, answer for THIS onion only.
            if not self._session_password:
                response = {"type": "auth_failed"}
            else:
                if self._auth_key is None:
                    self._auth_key = await asyncio.to_thread(
                        session_auth.auth_key, self._session_password, self._onion_host)
                await proto.send_msg(writer, {
                    "type": "auth",
                    "proof": session_auth.proof(self._auth_key, str(response.get("nonce", "")),
                                                self._crypto.public_key_b64),
                })
                response = await asyncio.wait_for(proto.recv_msg(reader), timeout=120)
        if response.get("type") == "auth_failed":
            log.warning("handshake: auth_failed (wrong session password)")
            self._on_event({"type": "auth_failed"})
            writer.close()
            return True
        if response.get("type") != "welcome":
            raise RuntimeError("Beklenmeyen handshake yanıtı")
        welcome = response

        self._crypto.unwrap_session_key(
            welcome["public_key"],
            welcome["nonce"],
            welcome["ciphertext"],
        )
        self._connected = True
        log.info("handshake complete → connected")

        # Signal the UI that the handshake completed. This mirrors the mobile
        # client and is what flips ChatSession.connected → True, which in turn
        # enables the keepalive ping timer.
        self._on_event({"type": "connected"})

        asyncio.create_task(self._read_loop(reader))
        self._writer_task = asyncio.create_task(self._writer_loop())
        # Independent keepalive: idle clients send no traffic, so without this
        # the Tor circuit is reaped after a few minutes and the session drops.
        # Runs regardless of UI state, matching the mobile client's heartbeat.
        asyncio.create_task(self._heartbeat())
        return True

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while self._connected:
                frame = await proto.recv_msg(reader)
                if frame.get("type") != "encrypted":
                    log.debug("recv non-encrypted frame: %s", frame.get("type"))
                    continue
                inner = self._crypto.decrypt(frame)
                log.debug("recv event: %s (nick=%s)", inner.get("type"), redact(inner.get("nick")))
                self._on_event(inner)
        except (asyncio.IncompleteReadError, ConnectionResetError) as e:
            self._connected = False
            log.warning("read loop ended (connection closed): %r", e)
            self._on_event({"type": "disconnected"})
        except Exception as e:
            self._connected = False
            log.error("read loop error: %r", e)
            self._on_event({"type": "disconnected"})

    async def _heartbeat(self) -> None:
        """Send a ping every 30s so the Tor circuit is not dropped while idle.
        The host answers with a pong (used for latency); an idle connection with
        no traffic would otherwise be reaped after a few minutes."""
        try:
            while self._connected:
                await asyncio.sleep(30)
                if not self._connected:
                    break
                self._enqueue(proto.make_ping(time.time()), _PRIO_CONTROL)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------
    #
    # All outgoing frames go through a single writer task (_writer_loop)
    # draining a priority queue, so exactly one coroutine ever touches
    # self._writer — writing to a StreamWriter from two coroutines at once
    # would interleave their bytes and corrupt the length-prefixed framing.
    # The priority split (_enqueue) is what keeps a large file/GIF transfer
    # from delaying ordinary chat/control frames: a chunk already being
    # written can't be interrupted, but the *next* item the loop picks up
    # will always be a pending control frame if one is queued.

    def _enqueue(self, payload: dict, priority: int) -> None:
        self._send_queue.put_nowait((priority, next(self._send_seq), payload))

    async def _writer_loop(self) -> None:
        try:
            while True:
                _, _, payload = await self._send_queue.get()
                if payload is _SHUTDOWN:
                    break
                try:
                    await self._send(payload)
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def _send(self, payload: dict) -> None:
        if not self._writer:
            log.warning("_send dropped (%s): writer=%s", payload.get("type"), self._writer is not None)
            return
        try:
            envelope = self._crypto.encrypt(payload)
            await proto.send_msg(self._writer, envelope)
            if payload.get("type") != "ping":
                log.debug("sent event: %s", payload.get("type"))
        except Exception as e:
            log.error("send failed (%s): %r", payload.get("type"), e)
            raise

    async def send_chat(self, content: str, msg_id: str | None = None,
                        reply_to_nick: str | None = None, reply_to_content: str | None = None,
                        disappear_secs: int = 0) -> None:
        self._enqueue(proto.make_chat(self._nick, content, msg_id, reply_to_nick, reply_to_content,
                                       disappear_secs), _PRIO_CONTROL)

    async def send_file(self, file_id: str, filename: str, mime: str, data: bytes) -> None:
        if not self._connected or not self._writer:
            return
        chunks = [data[i:i + proto.CHUNK_SIZE] for i in range(0, len(data), proto.CHUNK_SIZE)]
        total = len(chunks)
        self._enqueue(proto.make_file_start(self._nick, file_id, filename, mime, len(data), total), _PRIO_FILE)
        for i, chunk in enumerate(chunks):
            self._enqueue(proto.make_file_chunk(self._nick, file_id, i, base64.b64encode(chunk).decode()), _PRIO_FILE)
        self._enqueue(proto.make_file_end(self._nick, file_id), _PRIO_FILE)

    async def send_panic(self) -> None:
        if not self._connected or not self._writer:
            return
        self._enqueue(proto.make_panic(self._nick), _PRIO_CONTROL)

    async def send_typing(self, is_typing: bool) -> None:
        self._enqueue(proto.make_typing(self._nick, is_typing), _PRIO_CONTROL)

    async def send_delete(self, msg_id: str) -> None:
        self._enqueue(proto.make_delete(self._nick, msg_id), _PRIO_CONTROL)

    async def send_edit(self, msg_id: str, content: str) -> None:
        self._enqueue(proto.make_edit(self._nick, msg_id, content), _PRIO_CONTROL)

    async def send_ping(self, ts: float) -> None:
        self._enqueue(proto.make_ping(ts), _PRIO_CONTROL)

    async def disconnect(self) -> None:
        self._connected = False
        if self._writer:
            # Flush the leave frame through the same writer task rather than
            # sending it directly — a direct write here could interleave
            # with whatever _writer_loop is mid-send on, corrupting framing.
            self._enqueue(proto.make_leave(self._nick), _PRIO_CONTROL)
            self._send_queue.put_nowait((_PRIO_CONTROL, next(self._send_seq), _SHUTDOWN))
            if self._writer_task:
                try:
                    await asyncio.wait_for(self._writer_task, timeout=2.0)
                except Exception:
                    self._writer_task.cancel()
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._crypto.wipe()
