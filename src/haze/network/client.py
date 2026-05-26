"""
Join-mode asyncio client. Connects to host via Tor SOCKS5.
"""

import asyncio
import base64
import hashlib
from typing import Callable

from python_socks.async_.asyncio import Proxy

from ..crypto.e2e import SessionCrypto
from . import protocol as proto


def _hash_password(password: str) -> str:
    if not password:
        return ""
    return hashlib.sha256(b"haze-session-v1:" + password.encode()).hexdigest()


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
        self._password_hash = _hash_password(session_password)

        self._crypto = SessionCrypto()
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
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
            "password_hash": self._password_hash,
        })

        response = await asyncio.wait_for(proto.recv_msg(reader), timeout=60)
        if response.get("type") == "auth_failed":
            self._on_event({"type": "auth_failed"})
            writer.close()
            return
        if response.get("type") != "welcome":
            raise RuntimeError("Beklenmeyen handshake yanıtı")
        welcome = response

        self._crypto.unwrap_session_key(
            welcome["public_key"],
            welcome["nonce"],
            welcome["ciphertext"],
        )
        self._connected = True

        asyncio.create_task(self._read_loop(reader))

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while self._connected:
                frame = await proto.recv_msg(reader)
                if frame.get("type") != "encrypted":
                    continue
                inner = self._crypto.decrypt(frame)
                self._on_event(inner)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            self._connected = False
            self._on_event({"type": "disconnected"})
        except Exception:
            self._connected = False
            self._on_event({"type": "disconnected"})

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    async def _send(self, payload: dict) -> None:
        if not self._connected or not self._writer:
            return
        envelope = self._crypto.encrypt(payload)
        await proto.send_msg(self._writer, envelope)

    async def send_chat(self, content: str, msg_id: str | None = None) -> None:
        await self._send(proto.make_chat(self._nick, content, msg_id))

    async def send_file(self, file_id: str, filename: str, mime: str, data: bytes) -> None:
        if not self._connected or not self._writer:
            return
        chunks = [data[i:i + proto.CHUNK_SIZE] for i in range(0, len(data), proto.CHUNK_SIZE)]
        total = len(chunks)
        await self._send(proto.make_file_start(self._nick, file_id, filename, mime, len(data), total))
        for i, chunk in enumerate(chunks):
            await self._send(proto.make_file_chunk(self._nick, file_id, i, base64.b64encode(chunk).decode()))
        await self._send(proto.make_file_end(self._nick, file_id))

    async def send_panic(self) -> None:
        if not self._connected or not self._writer:
            return
        try:
            await self._send(proto.make_panic(self._nick))
        except Exception:
            pass

    async def send_typing(self, is_typing: bool) -> None:
        await self._send(proto.make_typing(self._nick, is_typing))

    async def send_delete(self, msg_id: str) -> None:
        await self._send(proto.make_delete(self._nick, msg_id))

    async def send_edit(self, msg_id: str, content: str) -> None:
        await self._send(proto.make_edit(self._nick, msg_id, content))

    async def send_ping(self, ts: float) -> None:
        await self._send(proto.make_ping(ts))

    async def disconnect(self) -> None:
        self._connected = False
        if self._writer:
            try:
                await self._send(proto.make_leave(self._nick))
            except Exception:
                pass
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._crypto.wipe()
