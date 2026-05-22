"""
Join-mode asyncio client. Connects to host via Tor SOCKS5.
"""

import asyncio
from typing import Callable

from python_socks.async_.asyncio import Proxy

from ..crypto.e2e import SessionCrypto
from . import protocol as proto


class ChatClient:
    def __init__(
        self,
        nick: str,
        onion_host: str,
        socks_port: int,
        on_event: Callable[[dict], None],
    ) -> None:
        self._nick = nick
        self._onion_host = onion_host.strip().rstrip("/")
        self._socks_port = socks_port
        self._on_event = on_event

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
            dest_port=80,
            timeout=120,
        )
        reader, writer = await asyncio.open_connection(sock=sock)
        self._writer = writer

        # Handshake
        await proto.send_msg(writer, {
            "type": "hello",
            "public_key": self._crypto.public_key_b64,
            "nick": self._nick,
        })

        welcome = await asyncio.wait_for(proto.recv_msg(reader), timeout=60)
        if welcome.get("type") != "welcome":
            raise RuntimeError("Beklenmeyen handshake yanıtı")

        self._crypto.unwrap_session_key(
            welcome["public_key"],
            welcome["nonce"],
            welcome["ciphertext"],
        )
        self._connected = True

        # Read loop
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

    async def send_chat(self, content: str) -> None:
        if not self._connected or not self._writer:
            return
        payload = proto.make_chat(self._nick, content)
        envelope = self._crypto.encrypt(payload)
        await proto.send_msg(self._writer, envelope)

    async def send_panic(self) -> None:
        if not self._connected or not self._writer:
            return
        payload = proto.make_panic(self._nick)
        envelope = self._crypto.encrypt(payload)
        try:
            await proto.send_msg(self._writer, envelope)
        except Exception:
            pass

    async def disconnect(self) -> None:
        self._connected = False
        if self._writer:
            # Graceful leave — server broadcasts "left" to remaining users
            try:
                payload = proto.make_leave(self._nick)
                envelope = self._crypto.encrypt(payload)
                await proto.send_msg(self._writer, envelope)
            except Exception:
                pass
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._crypto.wipe()
