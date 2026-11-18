"""
Host-mode asyncio TCP server.

Handshake sequence per client:
  C→S  {"type": "hello", "public_key": "<b64>", "nick": "<nick>"}
  S→C  {"type": "welcome", "public_key": "<b64>", "nonce": "<b64>", "ciphertext": "<b64>"}
       (ciphertext = session_key wrapped with ECDH-derived key)
  S→C  encrypted({"type": "userlist", "users": [...]})
  S→all encrypted({"type": "join", "nick": "<nick>"})

After handshake all frames are encrypted envelopes.
"""

import asyncio
import base64
import hashlib
import hmac
import itertools
import os
import time
from collections import deque
from typing import Callable

from ..crypto.e2e import SessionCrypto
from ..crypto import session_auth
from ..logging_setup import get_logger
from . import protocol as proto

log = get_logger("server")

# Outgoing send-queue priorities — lower sorts first (asyncio.PriorityQueue).
# A large file/GIF broadcast to one client must never delay a chat/control
# frame to that (or any other) client by more than the time to finish
# sending one chunk already in flight.
_PRIO_CONTROL = 0
_PRIO_FILE = 1
_FILE_TYPES = frozenset({"file_start", "file_chunk", "file_end"})

# Sentinel enqueued to make a per-client writer loop exit after flushing
# whatever was ahead of it.
_SHUTDOWN = object()


def _priority_for(payload: dict) -> int:
    return _PRIO_FILE if payload.get("type") in _FILE_TYPES else _PRIO_CONTROL


def _hash_password(password: str) -> str:
    if not password:
        return ""
    return hashlib.sha256(b"haze-session-v1:" + password.encode()).hexdigest()


class _PasswordThrottle:
    """Online-guessing brake for the session password.

    Shared by both join paths (native TCP and the browser gateway) so they
    cannot be played against each other. Checks run one at a time — opening
    many connections at once does not let a guesser try passwords in parallel
    — and after failures each check first waits 2, 4, 8, 16, then 30 s;
    failures older than WINDOW are forgotten.

    There is deliberately no hard lock-out. The previous version refused every
    password join after 20 failures in 10 minutes, which let anyone who knew
    the onion address keep the real participants out indefinitely by guessing
    wrong 20 times every 10 minutes.
    """

    WINDOW = 600.0

    def __init__(self) -> None:
        self._fails: deque[float] = deque()
        self._gate = asyncio.Lock()
        self._sleep = asyncio.sleep          # replaced by the tests

    @staticmethod
    def delay_for(failures: int) -> float:
        return 0.0 if failures <= 0 else float(min(2 ** min(failures, 5), 30))

    async def check(self, is_correct: Callable[[], bool]) -> bool:
        """True if `is_correct()` says so; every wrong answer slows the next."""
        async with self._gate:
            now = time.monotonic()
            while self._fails and now - self._fails[0] > self.WINDOW:
                self._fails.popleft()
            if self._fails:
                await self._sleep(self.delay_for(len(self._fails)))
            if is_correct():
                return True
            self._fails.append(time.monotonic())
            return False


class ChatServer:
    def __init__(
        self,
        host_nick: str,
        local_port: int,
        on_event: Callable[[dict], None],
        session_password: str = "",
        onion_address: str = "",
    ) -> None:
        self._host_nick = host_nick
        self._local_port = local_port
        self._on_event = on_event
        # v1 digest: still what old native clients and the browser page send.
        self._session_password_hash = _hash_password(session_password)
        # v2 key (see crypto/session_auth.py): bound to this host's onion
        # address, so it is derived once that address is known.
        self._session_password = session_password
        self._auth_key: bytes | None = None
        if onion_address:
            self.set_onion_address(onion_address)
        self._pw_throttle = _PasswordThrottle()


        # nick → (reader, writer, per-conn crypto)
        self._clients: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter, SessionCrypto]] = {}
        # Every nick handed out in this session, native and web alike, kept
        # after its owner leaves. A nick is the only identity the protocol has:
        # clients accept a delete/edit/file chunk only from the nick that wrote
        # the message or started the transfer, so a newcomer who could take a
        # departed user's nick could edit and delete everything they wrote.
        self._used_nicks: set[str] = {host_nick}
        self._server: asyncio.AbstractServer | None = None

        # Per-client outgoing queue + dedicated writer task — see _priority_for.
        self._client_queues: dict[str, asyncio.PriorityQueue] = {}
        self._client_writer_tasks: dict[str, asyncio.Task] = {}
        self._send_seq = itertools.count()

    def set_onion_address(self, onion_address: str) -> None:
        """The address clients reach this host at; their v2 proofs are bound
        to it. Without it a v2 join cannot be verified and is refused."""
        if self._session_password and session_auth.onion_id(onion_address):
            self._auth_key = session_auth.auth_key(self._session_password, onion_address)

    async def _password_ok(self, hello: dict, reader, writer) -> bool:
        """Step 1b of the handshake, for a password-protected session.

        A client that announces auth v2 gets a one-time challenge and answers
        with a proof bound to this onion and to its own public key; nothing it
        sends would open the session anywhere else. A client that does not
        (older desktop / mobile builds) still sends the v1 digest, which is
        accepted for compatibility — the browser page sends it too, and the
        page comes from this host, so there it reveals nothing new.
        """
        if hello.get("auth") == session_auth.VERSION:
            challenge = session_auth.new_challenge()
            await proto.send_msg(writer, {"type": "challenge", "nonce": challenge})
            answer = await asyncio.wait_for(proto.recv_msg(reader), timeout=60)
            given = str(answer.get("proof", "")) if answer.get("type") == "auth" else ""
            key = self._auth_key
            if key is None:
                log.warning("v2 join refused: this host's onion address is not set")
            expected = session_auth.proof(key, challenge, str(hello.get("public_key", ""))) if key else None
            return await self._pw_throttle.check(
                lambda: expected is not None and hmac.compare_digest(given, expected))
        given = str(hello.get("password_hash", ""))
        return await self._pw_throttle.check(
            lambda: hmac.compare_digest(given, self._session_password_hash))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host="127.0.0.1",
            port=self._local_port,
        )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for task in self._client_writer_tasks.values():
            task.cancel()
        self._client_writer_tasks.clear()
        self._client_queues.clear()
        for _nick, (_reader, writer, _crypto) in list(self._clients.items()):
            try:
                writer.close()
            except Exception:
                pass
        for _, _, conn_crypto in self._clients.values():
            conn_crypto.wipe()
        self._clients.clear()

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------
    #
    # Each client has its own outgoing queue drained by a dedicated writer
    # task (_client_writer_loop), so exactly one coroutine ever writes to a
    # given client's socket — concurrent writes would interleave their bytes
    # and corrupt the length-prefixed framing. _broadcast only enqueues;
    # _priority_for ensures a chat/control frame to a client always jumps
    # ahead of that client's still-pending file/GIF chunks.

    async def _send_encrypted(
        self,
        writer: asyncio.StreamWriter,
        conn_crypto: SessionCrypto,
        payload: dict,
    ) -> None:
        envelope = conn_crypto.encrypt(payload)
        await proto.send_msg(writer, envelope)

    def _enqueue_to(self, nick: str, payload: dict) -> None:
        queue = self._client_queues.get(nick)
        if queue is not None:
            queue.put_nowait((_priority_for(payload), next(self._send_seq), payload))

    async def _broadcast(self, payload: dict, exclude_nick: str | None = None) -> None:
        """Queue payload for delivery to every connected client."""
        for nick in list(self._clients.keys()):
            if nick == exclude_nick:
                continue
            self._enqueue_to(nick, payload)

    async def _client_writer_loop(self, nick: str) -> None:
        queue = self._client_queues[nick]
        try:
            while True:
                _, _, payload = await queue.get()
                if payload is _SHUTDOWN:
                    return
                entry = self._clients.get(nick)
                if not entry:
                    return
                _, writer, conn_crypto = entry
                try:
                    await self._send_encrypted(writer, conn_crypto, payload)
                except Exception:
                    break  # send failed — fall through and disconnect
        except asyncio.CancelledError:
            return
        if nick in self._clients:
            await self._disconnect_client(nick)

    # ------------------------------------------------------------------
    # Host sends messages
    # ------------------------------------------------------------------

    async def send_chat(self, content: str, msg_id: str | None = None,
                        reply_to_nick: str | None = None, reply_to_content: str | None = None,
                        disappear_secs: int = 0) -> None:
        payload = proto.make_chat(self._host_nick, content, msg_id, reply_to_nick, reply_to_content,
                                  disappear_secs)
        self._on_event(payload)
        await self._broadcast(payload)

    async def send_panic(self) -> None:
        payload = proto.make_panic(self._host_nick)
        self._on_event(payload)
        await self._broadcast(payload)

    async def send_file(self, file_id: str, filename: str, mime: str, data: bytes) -> None:
        chunks = [data[i:i + proto.CHUNK_SIZE] for i in range(0, len(data), proto.CHUNK_SIZE)]
        await self._broadcast(proto.make_file_start(
            self._host_nick, file_id, filename, mime, len(data), len(chunks)
        ))
        for i, chunk in enumerate(chunks):
            await self._broadcast(proto.make_file_chunk(
                self._host_nick, file_id, i, base64.b64encode(chunk).decode()
            ))
        await self._broadcast(proto.make_file_end(self._host_nick, file_id))

    async def kick_client(self, nick: str) -> None:
        if nick not in self._clients:
            return
        # Route "kicked" through the same per-client queue as everything
        # else (rather than a direct write) — the writer task may be
        # mid-send on a queued frame, and a second concurrent write to the
        # same socket would corrupt the framing.
        self._enqueue_to(nick, proto.make_kicked())
        queue = self._client_queues.get(nick)
        writer_task = self._client_writer_tasks.get(nick)
        if queue is not None:
            queue.put_nowait((_PRIO_CONTROL, next(self._send_seq), _SHUTDOWN))
        if writer_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(writer_task), timeout=2.0)
            except Exception:
                pass
        await self._disconnect_client(nick)

    async def send_typing(self, is_typing: bool) -> None:
        payload = proto.make_typing(self._host_nick, is_typing)
        await self._broadcast(payload)

    @staticmethod
    def web_traffic_key() -> bytes:
        """A fresh AES-GCM key for one browser connection (audit H14): no
        longer one key shared by every browser guest."""
        return os.urandom(32)

    async def receive_web_chat(
        self,
        nick: str,
        content: str,
        msg_id: str,
        reply_to_nick: str | None = None,
        reply_to_content: str | None = None,
    ) -> None:
        """Accept a message from a web client, notify Qt and forward to TCP clients."""
        payload = proto.make_chat(
            nick, content, msg_id,
            reply_to_nick=reply_to_nick, reply_to_content=reply_to_content,
        )
        self._on_event(payload)
        await self._broadcast(payload)

    async def receive_web_file(self, nick: str, payload: dict) -> None:
        """Relay one file frame (start/chunk/end) from a browser client.

        The nick is stamped here from the authenticated session, so a browser
        cannot attribute a transfer to someone else. Size and chunk limits are
        applied by the caller before this is reached.
        """
        payload["nick"] = nick
        self._on_event(payload)
        await self._broadcast(payload)

    async def receive_web_edit(self, nick: str, msg_id: str, content: str) -> None:
        """Edit requested by a web client, attributed to that client's nick."""
        payload = proto.make_edit(nick, msg_id, content)
        self._on_event(payload)
        await self._broadcast(payload)

    async def receive_web_delete(self, nick: str, msg_id: str) -> None:
        """Delete requested by a web client, attributed to that client's nick.

        Distinct from `send_delete`, which speaks for the host — a web guest
        deleting its own message must not appear to be the host doing it.
        """
        payload = proto.make_delete(nick, msg_id)
        self._on_event(payload)
        await self._broadcast(payload)

    async def receive_web_typing(self, nick: str, is_typing: bool) -> None:
        payload = proto.make_typing(nick, is_typing)
        self._on_event(payload)
        await self._broadcast(payload)

    async def send_delete(self, msg_id: str) -> None:
        payload = proto.make_delete(self._host_nick, msg_id)
        self._on_event(payload)
        await self._broadcast(payload)

    async def send_edit(self, msg_id: str, content: str) -> None:
        payload = proto.make_edit(self._host_nick, msg_id, content)
        self._on_event(payload)
        await self._broadcast(payload)

    # ------------------------------------------------------------------
    # Client handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        conn_crypto = SessionCrypto()
        nick = None
        try:
            # Step 1: receive hello
            hello = await asyncio.wait_for(proto.recv_msg(reader), timeout=30)
            if hello.get("type") != "hello":
                return
            client_pub = hello["public_key"]
            nick = self._sanitize_nick(hello.get("nick", "anonymous"))

            # Step 1b: password check (if session is protected)
            if self._session_password_hash:
                if not await self._password_ok(hello, reader, writer):
                    await proto.send_msg(writer, {"type": "auth_failed"})
                    return

            # Deduplicate nick. The suffix used to be len(clients)+1, taken
            # once and never re-checked, so after someone left it could name a
            # user who was still here ("bob", "carol", "bob_3"; carol leaves;
            # the next "bob" became "bob_3" too) — overwriting that user's
            # entry, message queue and writer task, and letting the newcomer
            # speak under an identity nobody could tell apart. Probe until free.
            # Nicks of users who already left count as taken too (see
            # _used_nicks): a returning user comes back as "bob_2".
            nick = self.claim_nick(nick)

            # Step 2: ECDH + wrap this connection's own key (audit H14).
            # There used to be one group key for everybody, so a user who left
            # or was kicked kept a key that still decrypted everyone else's
            # traffic. The host decrypts every frame and re-encrypts it per
            # recipient anyway, so each connection gets a key of its own
            # (and a fresh host X25519 key): whoever leaves takes a key that
            # opens nothing but their own past. Clients see no difference —
            # they unwrap whatever key their welcome carries.
            conn_crypto.generate_session_key()
            wrapped = conn_crypto.wrap_session_key(client_pub)
            welcome = {
                "type": "welcome",
                "public_key": conn_crypto.public_key_b64,
                "nonce": wrapped["nonce"],
                "ciphertext": wrapped["ciphertext"],
            }
            await proto.send_msg(writer, welcome)

            # Step 3: send current user list
            users = [self._host_nick] + list(self._clients.keys())
            await self._send_encrypted(writer, conn_crypto, proto.make_userlist(users))

            # Register client + start its dedicated writer task (see
            # _client_writer_loop) — from here on, every send to this client
            # must go through self._client_queues[nick]/_enqueue_to, never a
            # direct write, or the two could interleave bytes on the wire.
            self._clients[nick] = (reader, writer, conn_crypto)
            self._client_queues[nick] = asyncio.PriorityQueue()
            self._client_writer_tasks[nick] = asyncio.create_task(self._client_writer_loop(nick))

            # Step 4: broadcast join to everyone (including new client)
            join_payload = proto.make_join(nick)
            self._on_event(join_payload)
            await self._broadcast(join_payload)

            # Step 5: read loop
            while True:
                frame = await proto.recv_msg(reader)
                if frame.get("type") != "encrypted":
                    continue
                inner = conn_crypto.decrypt(frame)
                msg_type = inner.get("type")

                if msg_type == "chat":
                    inner["nick"] = nick
                    self._on_event(inner)
                    await self._broadcast(inner, exclude_nick=nick)

                elif msg_type in ("file_start", "file_chunk", "file_end"):
                    inner["nick"] = nick
                    self._on_event(inner)
                    await self._broadcast(inner, exclude_nick=nick)

                elif msg_type == "typing":
                    inner["nick"] = nick
                    self._on_event(inner)
                    await self._broadcast(inner, exclude_nick=nick)

                elif msg_type == "delete":
                    inner["nick"] = nick
                    self._on_event(inner)
                    await self._broadcast(inner, exclude_nick=nick)

                elif msg_type == "edit":
                    inner["nick"] = nick
                    self._on_event(inner)
                    await self._broadcast(inner, exclude_nick=nick)

                elif msg_type == "ping":
                    self._enqueue_to(nick, proto.make_pong(inner.get("ts", 0.0)))

                elif msg_type == "leave":
                    await self._disconnect_client(nick)
                    return

                elif msg_type == "panic":
                    # A guest's panic takes that guest out, not the room: only
                    # the host is told (as a notice); everyone else sees them
                    # leave. Relaying it as "panic" made every other client
                    # wipe and leave — any guest could end the session for all.
                    inner["nick"] = nick
                    self._on_event(inner)
                    return

        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.TimeoutError):
            pass
        except Exception:
            pass
        finally:
            if nick and nick in self._clients:
                await self._disconnect_client(nick)

    async def _disconnect_client(self, nick: str) -> None:
        entry = self._clients.pop(nick, None)
        self._client_queues.pop(nick, None)
        writer_task = self._client_writer_tasks.pop(nick, None)
        # Guard against a writer task cancelling itself: _client_writer_loop
        # calls _disconnect_client on its own send failure, which would
        # otherwise reach this line while running as `writer_task`.
        if writer_task is not None and writer_task is not asyncio.current_task() and not writer_task.done():
            writer_task.cancel()
        if entry:
            _, writer, crypto = entry
            try:
                writer.close()
            except Exception:
                pass
            crypto.wipe()
            leave_payload = proto.make_leave(nick)
            self._on_event(leave_payload)
            await self._broadcast(leave_payload)

    def claim_nick(self, wanted: str) -> str:
        """Reserve a nick nobody has had in this session, based on `wanted`.

        Shared with the web gateway, so native and browser users draw from one
        pool. Synchronous on purpose: check-and-add cannot be interleaved by
        another handshake on the event loop.
        """
        nick, n = wanted, 2
        while nick in self._used_nicks or nick in self._clients:
            nick = f"{wanted}_{n}"
            n += 1
        self._used_nicks.add(nick)
        return nick

    @staticmethod
    def _sanitize_nick(nick: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        sanitized = "".join(c for c in nick if c in allowed)[:20]
        return sanitized or "anon"
