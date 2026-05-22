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
from typing import Callable

from ..crypto.e2e import SessionCrypto
from . import protocol as proto


class ChatServer:
    def __init__(
        self,
        host_nick: str,
        local_port: int,
        on_event: Callable[[dict], None],
    ) -> None:
        self._host_nick = host_nick
        self._local_port = local_port
        self._on_event = on_event  # called in asyncio thread, emits Qt signal

        self._crypto = SessionCrypto()
        self._crypto.generate_session_key()

        # nick → (reader, writer, per-conn crypto)
        self._clients: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter, SessionCrypto]] = {}
        self._server: asyncio.AbstractServer | None = None

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
        for _nick, (_reader, writer, _crypto) in list(self._clients.items()):
            try:
                writer.close()
            except Exception:
                pass
        self._clients.clear()
        self._crypto.wipe()

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    async def _send_encrypted(
        self,
        writer: asyncio.StreamWriter,
        conn_crypto: SessionCrypto,
        payload: dict,
    ) -> None:
        envelope = conn_crypto.encrypt(payload)
        await proto.send_msg(writer, envelope)

    async def _broadcast(self, payload: dict, exclude_nick: str | None = None) -> None:
        """Encrypt and send payload to every connected client."""
        dead = []
        for nick, (_, writer, conn_crypto) in self._clients.items():
            if nick == exclude_nick:
                continue
            try:
                await self._send_encrypted(writer, conn_crypto, payload)
            except Exception:
                dead.append(nick)
        for nick in dead:
            await self._disconnect_client(nick)

    # ------------------------------------------------------------------
    # Host sends a message (no TCP roundtrip needed)
    # ------------------------------------------------------------------

    async def send_chat(self, content: str) -> None:
        payload = proto.make_chat(self._host_nick, content)
        self._on_event(payload)
        await self._broadcast(payload)

    async def send_panic(self) -> None:
        payload = proto.make_panic(self._host_nick)
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

            # Deduplicate nick
            if nick in self._clients or nick == self._host_nick:
                nick = f"{nick}_{len(self._clients)+1}"

            # Step 2: ECDH + wrap session key
            wrapped = self._crypto.wrap_session_key(client_pub)
            welcome = {
                "type": "welcome",
                "public_key": self._crypto.public_key_b64,
                "nonce": wrapped["nonce"],
                "ciphertext": wrapped["ciphertext"],
            }
            # conn_crypto needs the session key to encrypt further messages
            conn_crypto.set_session_key(bytes(self._crypto._session_key))
            await proto.send_msg(writer, welcome)

            # Step 3: send current user list
            users = [self._host_nick] + list(self._clients.keys())
            await self._send_encrypted(writer, conn_crypto, proto.make_userlist(users))

            # Register client
            self._clients[nick] = (reader, writer, conn_crypto)

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
                    inner["nick"] = nick  # trust server-side nick
                    self._on_event(inner)
                    await self._broadcast(inner, exclude_nick=nick)

                elif msg_type == "leave":
                    # Client is gracefully leaving — disconnect broadcasts to others
                    await self._disconnect_client(nick)
                    return

                elif msg_type == "panic":
                    inner["nick"] = nick
                    self._on_event(inner)
                    await self._broadcast(inner)
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

    @staticmethod
    def _sanitize_nick(nick: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        sanitized = "".join(c for c in nick if c in allowed)[:20]
        return sanitized or "anon"
