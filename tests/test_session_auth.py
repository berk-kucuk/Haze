"""Joining a password session proves the password without handing over a
reusable secret (audit H6).

v1 sent SHA-256("haze-session-v1:" + password) to whatever address it was
given. That digest opened the session by itself, so a lookalike .onion only had
to receive it once. v2 answers a one-time challenge with a proof bound to the
onion the client dialled.

A real ChatClient joins a real ChatServer; a tiny SOCKS5 server stands in for
Tor and records every byte the client sends.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

_HOME = tempfile.mkdtemp(prefix="haze-test-home-")
os.environ["HOME"] = _HOME
os.environ["XDG_STATE_HOME"] = os.path.join(_HOME, ".local", "state")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_HOME, ".config")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from haze.crypto import session_auth  # noqa: E402
from haze.crypto.e2e import SessionCrypto  # noqa: E402
from haze.network import protocol as proto  # noqa: E402
from haze.network.client import ChatClient  # noqa: E402
from haze.network.server import ChatServer  # noqa: E402

REAL = "a" * 56 + ".onion"
FAKE = "a" * 55 + "b.onion"          # one character off
PASSWORD = "correct horse battery staple"
V1_DIGEST = hashlib.sha256(b"haze-session-v1:" + PASSWORD.encode()).hexdigest()


async def _no_sleep(_):
    pass


class _Socks5:
    """CONNECT to anything → relay to `target`; record what the client sent."""

    def __init__(self, target_port: int):
        self.target = target_port
        self.sent = bytearray()
        self.asked: list[str] = []

    async def _handle(self, r, w):
        _, n = await r.readexactly(2)
        await r.readexactly(n)
        w.write(b"\x05\x00")
        _, _, _, atyp = await r.readexactly(4)
        host = (await r.readexactly((await r.readexactly(1))[0])).decode() if atyp == 3 else ""
        await r.readexactly(2)
        self.asked.append(host)
        ur, uw = await asyncio.open_connection("127.0.0.1", self.target)
        w.write(b"\x05\x00\x00\x01" + bytes(6))

        async def pipe(a, b, record):
            try:
                while data := await a.read(65536):
                    if record:
                        self.sent += data
                    b.write(data)
                    await b.drain()
            except ConnectionError:
                pass
            finally:
                b.close()
        await asyncio.gather(pipe(r, uw, True), pipe(ur, w, False))

    async def start(self) -> int:
        self.srv = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.srv.sockets[0].getsockname()[1]


class AuthTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events: list[dict] = []
        self.server = ChatServer("host", 0, self.events.append,
                                 session_password=PASSWORD, onion_address=REAL)
        self.server._pw_throttle._sleep = _no_sleep
        self.server._server = await asyncio.start_server(
            self.server._handle_client, host="127.0.0.1", port=0)
        self.port = self.server._server.sockets[0].getsockname()[1]
        self.clients: list[ChatClient] = []
        self.writers: list = []

    async def asyncTearDown(self):
        for c in self.clients:
            c._connected = False
            if c._writer:
                c._writer.close()
        for w in self.writers:
            w.close()
        await asyncio.wait_for(self.server.stop(), 10)

    async def client_join(self, password: str, address: str = REAL, port: int | None = None):
        """A real ChatClient through SOCKS. Returns (first lifecycle event, relay)."""
        socks = _Socks5(port or self.port)
        socks_port = await socks.start()
        got: list[dict] = []
        c = ChatClient("bob", address, socks_port, got.append, session_password=password)
        self.clients.append(c)
        await asyncio.wait_for(c._attempt_connect(), 30)
        for _ in range(100):
            if any(e["type"] in ("connected", "auth_failed") for e in got):
                break
            await asyncio.sleep(0.01)
        first = next(e["type"] for e in got if e["type"] in ("connected", "auth_failed"))
        socks.srv.close()
        return first, socks

    async def raw(self, port: int | None = None):
        r, w = await asyncio.open_connection("127.0.0.1", port or self.port)
        self.writers.append(w)
        return r, w


class JoinTests(AuthTestCase):
    async def test_right_password_joins(self):
        first, socks = await self.client_join(PASSWORD)
        self.assertEqual(first, "connected")
        self.assertEqual(socks.asked, [REAL])

    async def test_wrong_password_is_refused(self):
        first, _ = await self.client_join("wrong")
        self.assertEqual(first, "auth_failed")

    async def test_no_password_is_refused(self):
        first, _ = await self.client_join("")
        self.assertEqual(first, "auth_failed")

    async def test_address_typed_any_way(self):
        for typed in ("a" * 56, "http://" + REAL.upper() + "/", REAL + ":5222"):
            first, _ = await self.client_join(PASSWORD, address=typed)
            self.assertEqual(first, "connected", typed)

    async def test_nothing_reusable_leaves_the_client(self):
        _, socks = await self.client_join(PASSWORD)
        sent = bytes(socks.sent)
        self.assertNotIn(V1_DIGEST.encode(), sent, "the v1 digest was sent")
        self.assertNotIn(PASSWORD.encode(), sent)
        self.assertNotIn(b"password_hash", sent)

    async def test_old_clients_still_join(self):
        r, w = await self.raw()
        await proto.send_msg(w, {"type": "hello", "public_key": SessionCrypto().public_key_b64,
                                 "nick": "old", "password_hash": V1_DIGEST})
        self.assertEqual((await proto.recv_msg(r))["type"], "welcome")

    async def test_a_proof_is_good_once(self):
        crypto = SessionCrypto()
        key = session_auth.auth_key(PASSWORD, REAL)
        r, w = await self.raw()
        await proto.send_msg(w, {"type": "hello", "public_key": crypto.public_key_b64,
                                 "nick": "x", "auth": 2})
        nonce = (await proto.recv_msg(r))["nonce"]
        proof = session_auth.proof(key, nonce, crypto.public_key_b64)
        await proto.send_msg(w, {"type": "auth", "proof": proof})
        self.assertEqual((await proto.recv_msg(r))["type"], "welcome")
        # Replayed on a new connection: new challenge, old proof.
        r2, w2 = await self.raw()
        await proto.send_msg(w2, {"type": "hello", "public_key": crypto.public_key_b64,
                                  "nick": "x", "auth": 2})
        nonce2 = (await proto.recv_msg(r2))["nonce"]
        self.assertNotEqual(nonce, nonce2)
        await proto.send_msg(w2, {"type": "auth", "proof": proof})
        self.assertEqual((await proto.recv_msg(r2))["type"], "auth_failed")

    async def test_host_without_its_address_refuses_v2(self):
        self.server._auth_key = None
        first, _ = await self.client_join(PASSWORD)
        self.assertEqual(first, "auth_failed")


class LookalikeOnionTests(AuthTestCase):
    """A fake host at FAKE gets the victim to join it with the real password."""

    async def _mitm(self, on_hello):
        """Fake host that relays to the real one; returns its port and a log."""
        log: dict = {}

        async def handle(r, w):
            hello = await proto.recv_msg(r)
            log["hello"] = hello
            rr, rw = await asyncio.open_connection("127.0.0.1", self.port)
            self.writers.append(rw)
            await on_hello(hello, r, w, rr, rw, log)
        srv = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.addAsyncCleanup(self._close, srv)
        return srv.sockets[0].getsockname()[1], log

    @staticmethod
    async def _close(srv):
        srv.close()

    async def test_relaying_the_challenge_gets_the_attacker_nothing(self):
        async def relay(hello, r, w, rr, rw, log):
            await proto.send_msg(rw, hello)                 # victim's own key and nick
            challenge = await proto.recv_msg(rr)            # the REAL host's challenge
            await proto.send_msg(w, challenge)
            answer = await proto.recv_msg(r)                # victim answers for FAKE
            await proto.send_msg(rw, answer)
            log["real_host_said"] = (await proto.recv_msg(rr))["type"]
            await proto.send_msg(w, {"type": "auth_failed"})
        port, log = await self._mitm(relay)
        await self.client_join(PASSWORD, address=FAKE, port=port)
        self.assertEqual(log["real_host_said"], "auth_failed")

    async def test_what_a_fake_host_collects_does_not_open_the_session(self):
        async def collect(hello, r, w, rr, rw, log):
            await proto.send_msg(w, {"type": "challenge", "nonce": "AAAA"})
            log["answer"] = await proto.recv_msg(r)
            await proto.send_msg(w, {"type": "auth_failed"})
        port, log = await self._mitm(collect)
        await self.client_join(PASSWORD, address=FAKE, port=port)
        self.assertNotIn("password_hash", log["hello"])
        # Everything collected, offered to the real host both ways:
        stolen = log["answer"]["proof"]
        r, w = await self.raw()
        await proto.send_msg(w, {"type": "hello", "public_key": log["hello"]["public_key"],
                                 "nick": "eve", "password_hash": stolen})
        self.assertEqual((await proto.recv_msg(r))["type"], "auth_failed")
        r, w = await self.raw()
        await proto.send_msg(w, {"type": "hello", "public_key": log["hello"]["public_key"],
                                 "nick": "eve", "auth": 2})
        await proto.recv_msg(r)
        await proto.send_msg(w, {"type": "auth", "proof": stolen})
        self.assertEqual((await proto.recv_msg(r))["type"], "auth_failed")


class OnionIdTests(unittest.TestCase):
    def test_forms(self):
        base = "a" * 56 + ".onion"
        for v in ("a" * 56, base, base.upper(), f"http://{base}/", f"{base}:5222",
                  f"  https://{base}/x?y#z "):
            self.assertEqual(session_auth.onion_id(v), base, v)
        self.assertEqual(session_auth.onion_id(""), "")

    def test_key_is_bound_to_the_address(self):
        self.assertNotEqual(session_auth.auth_key(PASSWORD, REAL),
                            session_auth.auth_key(PASSWORD, FAKE))

    def test_known_vector(self):
        """Pinned so the Kotlin twin (SessionAuthTest.kt) can check the same bytes."""
        key = session_auth.auth_key("pw", "x" * 56)
        self.assertEqual(session_auth.proof(key, "Tk9OQ0U=", "UFVC"), KNOWN_PROOF)


KNOWN_PROOF = "9b8fd1426b4fa54a4dfedc2e7d524ed5d5bf5c3929b795501b487f9545a91efc"

if __name__ == "__main__":
    unittest.main(verbosity=2)
