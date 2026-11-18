"""Who may change what in a session (audit findings H1, H2).

The host stamps every relayed event with the sender's own nick; receivers must
then apply a delete/edit only from a message's author, and file chunks only
from the transfer's sender. For a nick to identify one person, the host must
also never give out a nick twice in a session.

Runs without Tor, without a display (Qt offscreen) and without touching the
real home directory:  python -m unittest discover -s tests
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Before any haze import: settings/vault/log paths resolve under $HOME.
_HOME = tempfile.mkdtemp(prefix="haze-test-home-")
os.environ["HOME"] = _HOME
os.environ["XDG_STATE_HOME"] = os.path.join(_HOME, ".local", "state")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_HOME, ".config")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from haze.crypto.e2e import SessionCrypto  # noqa: E402
from haze.network import protocol as proto  # noqa: E402
from haze.network.server import ChatServer  # noqa: E402


# ── host: nicks are never handed out twice ─────────────────────────────────

class NickPoolTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.events: list[dict] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.server = ChatServer("host", 0, self.events.append)
        self.server._local_port = 0
        self.server._server = await asyncio.start_server(
            self.server._handle_client, host="127.0.0.1", port=0)
        self.port = self.server._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self) -> None:
        # Close our ends first, also when an assertion failed mid-test:
        # wait_closed() inside stop() waits for every open connection.
        for w in self.writers:
            w.close()
        await asyncio.wait_for(self.server.stop(), 10)

    async def join(self, nick: str):
        """A real native client: hello, ECDH, welcome, encrypted userlist."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(writer)
        crypto = SessionCrypto()
        await proto.send_msg(writer, {"type": "hello", "public_key": crypto.public_key_b64,
                                      "nick": nick, "password_hash": ""})
        welcome = await asyncio.wait_for(proto.recv_msg(reader), 5)
        crypto.unwrap_session_key(welcome["public_key"], welcome["nonce"], welcome["ciphertext"])
        await asyncio.wait_for(proto.recv_msg(reader), 5)          # userlist
        joined = await self._next_event("join")
        return reader, writer, crypto, joined["nick"]

    async def _next_event(self, kind: str) -> dict:
        for _ in range(200):
            for i, ev in enumerate(self.events):
                if ev.get("type") == kind:
                    return self.events.pop(i)
            await asyncio.sleep(0.01)
        self.fail(f"no {kind} event")

    async def test_a_departed_users_nick_is_not_given_out_again(self):
        _r, w, _c, first = await self.join("bob")
        self.assertEqual(first, "bob")
        w.close()
        await self._next_event("leave")
        _r2, w2, _c2, second = await self.join("bob")
        self.assertEqual(second, "bob_2", "a newcomer took over the departed bob's identity")
        w2.close()

    async def test_nick_of_a_present_user_or_the_host_is_never_given(self):
        _r, w1, _c, a = await self.join("carol")
        _r, w2, _c, b = await self.join("carol")
        _r, w3, _c, h = await self.join("host")
        self.assertEqual((a, b, h), ("carol", "carol_2", "host_2"))
        for w in (w1, w2, w3):
            w.close()

    async def test_relayed_events_carry_the_senders_own_nick(self):
        _r, w, c, nick = await self.join("mallory")
        # Mallory claims to be someone else in the inner payload.
        await proto.send_msg(w, c.encrypt({"type": "delete", "nick": "host", "msg_id": "m1"}))
        ev = await self._next_event("delete")
        self.assertEqual(ev["nick"], nick)
        w.close()

    def test_web_and_native_share_one_pool(self):
        s = self.server
        self.assertEqual(s.claim_nick("[web]eve"), "[web]eve")
        self.assertEqual(s.claim_nick("[web]eve"), "[web]eve_2")
        self.assertEqual(s.claim_nick("eve"), "eve")


# ── receivers: only the author may delete/edit, only the sender may add ────

class _Host:
    """The bits of MainWindow that _handle_session_event reaches for."""

    def __init__(self):
        self._settings = {"blur_messages": False, "disappearing_messages": 0}
        self.appended: list = []

    def _append_widget(self, session, widget, animate=False):
        self.appended.append(widget)

    def _append_system(self, session, text):
        pass

    def _notify_message(self, nick, content):
        pass

    def _fade_slogan(self, session):
        pass

    def _request_delete(self, session, mid):
        pass

    def _request_edit(self, session, mid, content):
        pass

    def _set_reply(self, session, nick, content):
        pass


class ReceiverRulesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from haze.ui import main_window as mw
        cls.app = QApplication.instance() or QApplication([])
        cls.mw = mw

    def setUp(self):
        self.host = _Host()
        self.s = self.mw.ChatSession("join", "me")
        self.s.typing_bar = None

    def ev(self, event: dict) -> None:
        self.mw.MainWindow._handle_session_event(self.host, self.s, dict(event))

    def message(self, msg_id: str) -> dict:
        return next(m for m in self.s.messages if m.get("msg_id") == msg_id)

    def chat(self, nick: str, msg_id: str, content: str) -> None:
        self.ev({"type": "chat", "nick": nick, "msg_id": msg_id, "content": content})

    # H1 ─ delete / edit

    def test_only_the_author_can_delete(self):
        self.chat("alice", "m1", "hello")
        self.ev({"type": "delete", "nick": "bob", "msg_id": "m1"})
        self.assertFalse(self.message("m1").get("deleted"), "bob deleted alice's message")
        self.ev({"type": "delete", "nick": "alice", "msg_id": "m1"})
        self.assertTrue(self.message("m1").get("deleted"))

    def test_only_the_author_can_edit(self):
        self.chat("alice", "m1", "hello")
        self.ev({"type": "edit", "nick": "bob", "msg_id": "m1", "content": "I owe bob 100"})
        self.assertEqual(self.message("m1")["content"], "hello", "bob rewrote alice's message")
        self.assertEqual(self.s.msg_widgets["m1"]._content, "hello")
        self.ev({"type": "edit", "nick": "alice", "msg_id": "m1", "content": "hello!"})
        self.assertEqual(self.message("m1")["content"], "hello!")

    def test_a_reused_msg_id_cannot_hijack_a_message(self):
        self.chat("alice", "m1", "hello")
        widget = self.s.msg_widgets["m1"]
        self.chat("bob", "m1", "copy")
        self.assertEqual(len(self.s.messages), 1, "the impostor message was accepted")
        self.assertIs(self.s.msg_widgets["m1"], widget)
        self.assertEqual(self.s.msg_owners["m1"], "alice")

    def test_own_messages_sent_from_this_client_stay_editable(self):
        # Join mode renders own messages locally and registers the owner;
        # the host echoes our edits of our own messages to others only.
        self.s.msg_owners["mine"] = "me"
        self.s.messages.append({"type": "chat", "nick": "me", "content": "x", "msg_id": "mine"})
        self.ev({"type": "edit", "nick": "me", "msg_id": "mine", "content": "y"})
        self.assertEqual(self.message("mine")["content"], "y")

    # H2 ─ file transfers

    def start(self, nick: str, fid: str, chunks: int = 2) -> None:
        self.ev({"type": "file_start", "nick": nick, "file_id": fid, "filename": "f.txt",
                 "mime": "text/plain", "total_size": 10, "total_chunks": chunks})

    def chunk(self, nick: str, fid: str, idx: int, data: bytes) -> None:
        self.ev({"type": "file_chunk", "nick": nick, "file_id": fid, "chunk_index": idx,
                 "data": base64.b64encode(data).decode()})

    def test_second_file_start_cannot_take_over_a_transfer(self):
        self.start("alice", "f1")
        self.start("bob", "f1")
        self.assertEqual(self.s.file_buffers["f1"]["nick"], "alice")

    def test_chunks_from_anyone_but_the_sender_are_ignored(self):
        self.start("alice", "f1")
        self.chunk("bob", "f1", 0, b"EVIL!")          # would win slot 0 (first wins)
        self.chunk("alice", "f1", 0, b"hello")
        self.chunk("alice", "f1", 1, b"world")
        buf = self.s.file_buffers["f1"]
        widget = buf["widget"]
        got = {}
        widget.set_ready = lambda data: got.setdefault("data", data)
        self.ev({"type": "file_end", "nick": "bob", "file_id": "f1"})
        self.assertIn("f1", self.s.file_buffers, "bob ended alice's transfer early")
        self.ev({"type": "file_end", "nick": "alice", "file_id": "f1"})
        self.assertNotIn("f1", self.s.file_buffers)
        self.assertEqual(got.get("data"), b"helloworld")

    def test_a_transfer_missing_a_chunk_is_not_assembled(self):
        self.start("alice", "f2", chunks=3)
        self.chunk("alice", "f2", 0, b"aa")
        self.chunk("alice", "f2", 2, b"cc")             # chunk 1 never comes
        widget = self.s.file_buffers["f2"]["widget"]
        got = {}
        widget.set_ready = lambda data: got.setdefault("data", data)
        self.ev({"type": "file_end", "nick": "alice", "file_id": "f2"})
        self.assertNotIn("data", got, "a truncated file was presented as complete")
        self.assertNotIn("f2", self.s.file_buffers)


# ── the password brake (H5): serial, slowing, never a lock-out ──────────────

class ThrottleTestCase(unittest.IsolatedAsyncioTestCase):
    def make(self):
        from haze.network.server import _PasswordThrottle
        th = _PasswordThrottle()
        self.slept: list[float] = []

        async def fake_sleep(secs):
            self.slept.append(secs)
            await asyncio.sleep(0)
        th._sleep = fake_sleep
        return th

    async def test_delays_grow_then_cap(self):
        th = self.make()
        for _ in range(7):
            self.assertFalse(await th.check(lambda: False))
        self.assertEqual(self.slept, [2.0, 4.0, 8.0, 16.0, 30.0, 30.0])

    async def test_no_lock_out_after_many_failures(self):
        th = self.make()
        for _ in range(50):
            await th.check(lambda: False)
        self.assertTrue(await th.check(lambda: True),
                        "the right password was refused after others guessed wrong")

    async def test_checks_never_run_in_parallel(self):
        th = self.make()
        await th.check(lambda: False)                 # one failure: later checks wait
        inside = peak = 0

        async def slow_sleep(secs):
            nonlocal inside, peak
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.01)
            inside -= 1
        th._sleep = slow_sleep
        results = await asyncio.gather(*(th.check(lambda: False) for _ in range(10)))
        self.assertEqual(results, [False] * 10)
        self.assertEqual(peak, 1, f"{peak} guesses were being checked at the same time")

    async def test_failures_age_out(self):
        th = self.make()
        await th.check(lambda: False)
        th._fails[0] -= th.WINDOW + 1                 # that failure is old now
        await th.check(lambda: True)
        self.assertEqual(self.slept, [], "an old failure still slowed a fresh check")


class PasswordJoinTestCase(unittest.IsolatedAsyncioTestCase):
    """The native join path through the throttle, end to end."""

    async def asyncSetUp(self) -> None:
        self.server = ChatServer("host", 0, lambda ev: None, session_password="s3cret")
        self.server._pw_throttle._sleep = lambda secs: asyncio.sleep(0)
        self.server._server = await asyncio.start_server(
            self.server._handle_client, host="127.0.0.1", port=0)
        self.port = self.server._server.sockets[0].getsockname()[1]
        self.writers = []

    async def asyncTearDown(self) -> None:
        for w in self.writers:
            w.close()
        await asyncio.wait_for(self.server.stop(), 10)

    async def hello(self, password: str) -> str:
        from haze.network.server import _hash_password
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(writer)
        await proto.send_msg(writer, {"type": "hello", "public_key": SessionCrypto().public_key_b64,
                                      "nick": "x", "password_hash": _hash_password(password)})
        return (await asyncio.wait_for(proto.recv_msg(reader), 5))["type"]

    async def test_wrong_then_right(self):
        for _ in range(25):                           # more than the old lock-out (20)
            self.assertEqual(await self.hello("guess"), "auth_failed")
        self.assertEqual(await self.hello("s3cret"), "welcome")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class PerConnectionKeyTestCase(NickPoolTestCase):
    """H14: one group key for everybody meant a user who left — or was
    kicked — kept a key that decrypted everyone else's traffic."""

    async def test_every_connection_has_its_own_key(self):
        _r1, _w1, c1, _ = await self.join("alice")
        _r2, _w2, c2, _ = await self.join("bob")
        self.assertNotEqual(bytes(c1._session_key), bytes(c2._session_key))

    async def test_a_departed_users_key_opens_nothing_sent_to_others(self):
        r1, w1, c1, _ = await self.join("alice")
        r2, _w2, c2, _ = await self.join("bob")
        leaver_key = bytes(c2._session_key)
        _w2.close()
        await self._next_event("leave")
        # The host now says something; alice receives it.
        await self.server.send_chat("after bob left")
        got = None
        for _ in range(20):
            frame = await asyncio.wait_for(proto.recv_msg(r1), 5)
            inner = c1.decrypt(frame)
            if inner.get("type") == "chat":
                got = frame
                break
        self.assertIsNotNone(got)
        thief = SessionCrypto()
        thief.set_session_key(leaver_key)
        with self.assertRaises(Exception):
            thief.decrypt(got)

    def test_browser_guests_get_their_own_keys(self):
        self.assertNotEqual(ChatServer.web_traffic_key(), ChatServer.web_traffic_key())
