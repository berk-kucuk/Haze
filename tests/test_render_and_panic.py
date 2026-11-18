"""What peers can make this client show and do (audit findings H3, H4).

H3 — a peer's message, nick or file name was shown by QLabel's AutoText, so
     "<b>…</b>", links, local images and fake system lines rendered as HTML.
H4 — a guest's panic was relayed to everyone as "panic", and every other
     client wiped and left: any guest could end the session for all.

python -m unittest discover -s tests   (Qt offscreen, no Tor, no real $HOME)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HOME = tempfile.mkdtemp(prefix="haze-test-home-")
os.environ["HOME"] = _HOME
os.environ["XDG_STATE_HOME"] = os.path.join(_HOME, ".local", "state")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_HOME, ".config")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from haze.crypto.e2e import SessionCrypto  # noqa: E402
from haze.network import protocol as proto  # noqa: E402
from haze.network.server import ChatServer  # noqa: E402

EVIL = '<b>⚠ HOST PRESSED PANIC</b> <img src="/etc/hostname"> <a href="http://x">click</a>'


def _labels(widget):
    from PyQt6.QtWidgets import QLabel
    return widget.findChildren(QLabel)


class RenderingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from haze.ui import main_window as mw
        cls.app = QApplication.instance() or QApplication([])
        cls.mw = mw

    def assertShownAsText(self, widget, needle):
        from PyQt6.QtCore import Qt
        hits = [lb for lb in _labels(widget) if needle in lb.text()]
        self.assertTrue(hits, f"{needle!r} is not shown at all")
        for lb in hits:
            self.assertEqual(lb.textFormat(), Qt.TextFormat.PlainText,
                             f"{lb.text()[:40]!r} would be rendered as HTML")

    def test_message_body_and_code_block(self):
        b = self.mw.MessageBubble("mallory", EVIL + "\n```" + EVIL + "```", is_me=False, msg_id="m1")
        self.assertShownAsText(b, "<b>")

    def test_nick_and_reply_preview(self):
        b = self.mw.MessageBubble("<i>x</i>", "hi", is_me=False, msg_id="m1",
                                  reply_to_nick="<u>y</u>", reply_to_content=EVIL)
        self.assertShownAsText(b, "<I>X</I>")          # the nick label is upper-cased
        self.assertShownAsText(b, "<b>")

    def test_system_line_and_panic_banner(self):
        self.assertShownAsText(self.mw.SystemMessage(f"{EVIL} joined"), "<b>")
        self.assertShownAsText(self.mw.PanicBanner("<b>x</b>"), "<B>X</B>")

    def test_file_name(self):
        f = self.mw.FileMessage("<b>n</b>", "<img src=/x>.png", 10, "image/png")
        self.assertShownAsText(f, "<img")

    def test_notifications_carry_no_markup(self):
        out = self.mw._notification_safe("eve: " + EVIL + " & more")
        for ch in "<>&":
            self.assertNotIn(ch, out)
        self.assertIn("HOST PRESSED PANIC", out)


class _Host:
    def __init__(self):
        self._settings = {}
        self.system: list[str] = []
        self.dialogs: list[str] = []

    def _append_system(self, session, text):
        self.system.append(text)

    def _append_widget(self, *a, **k):
        pass

    def _show_panic_dialog(self, nick):
        self.dialogs.append(nick)

    def _add_user_to_list(self, session, nick):
        pass


class PanicClientTestCase(unittest.TestCase):
    """A joined client obeys a panic only from the host."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from haze.ui import main_window as mw
        cls.app = QApplication.instance() or QApplication([])
        cls.mw = mw

    def setUp(self):
        self.host = _Host()
        self.s = self.mw.ChatSession("join", "me")
        self.ev({"type": "userlist", "users": ["boss", "alice", "me"]})

    def ev(self, event):
        self.mw.MainWindow._handle_session_event(self.host, self.s, dict(event))

    def test_a_guests_panic_does_not_end_my_session(self):
        self.ev({"type": "panic", "nick": "alice"})
        self.assertEqual(self.host.dialogs, [], "a guest made me wipe and leave")
        self.assertTrue(any("alice" in line for line in self.host.system))

    def test_the_hosts_panic_does(self):
        self.ev({"type": "panic", "nick": "boss"})
        self.assertEqual(self.host.dialogs, ["boss"])

    def test_the_host_is_the_first_userlist_entry_only(self):
        # A later userlist (from nobody in particular) cannot move the host.
        self.ev({"type": "userlist", "users": ["alice", "boss"]})
        self.ev({"type": "panic", "nick": "alice"})
        self.assertEqual(self.host.dialogs, [])


class PanicServerTestCase(unittest.IsolatedAsyncioTestCase):
    """The host tells nobody else about a guest's panic."""

    async def asyncSetUp(self):
        self.events: list[dict] = []
        self.server = ChatServer("boss", 0, self.events.append)
        self.server._server = await asyncio.start_server(
            self.server._handle_client, host="127.0.0.1", port=0)
        self.port = self.server._server.sockets[0].getsockname()[1]
        self.writers = []

    async def asyncTearDown(self):
        for w in self.writers:
            w.close()
        await asyncio.wait_for(self.server.stop(), 10)

    async def join(self, nick):
        r, w = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(w)
        c = SessionCrypto()
        await proto.send_msg(w, {"type": "hello", "public_key": c.public_key_b64, "nick": nick})
        welcome = await asyncio.wait_for(proto.recv_msg(r), 5)
        c.unwrap_session_key(welcome["public_key"], welcome["nonce"], welcome["ciphertext"])
        return r, w, c

    async def frames(self, r, c, seconds=0.5):
        out = []
        try:
            while True:
                f = await asyncio.wait_for(proto.recv_msg(r), seconds)
                out.append(c.decrypt(f))
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return out

    async def test_guest_panic_reaches_only_the_host(self):
        ra, wa, ca = await self.join("alice")
        rb, wb, cb = await self.join("bob")
        await self.frames(rb, cb, 0.3)                    # bob's userlist + joins
        await proto.send_msg(wa, ca.encrypt({"type": "panic", "nick": "alice"}))
        seen = [f["type"] for f in await self.frames(rb, cb)]
        self.assertNotIn("panic", seen, "bob was told to wipe because alice panicked")
        self.assertIn("leave", seen)
        self.assertTrue(any(e.get("type") == "panic" and e.get("nick") == "alice" for e in self.events))

    async def test_host_panic_still_reaches_everyone(self):
        rb, wb, cb = await self.join("bob")
        await self.frames(rb, cb, 0.3)
        await self.server.send_panic()
        seen = await self.frames(rb, cb)
        self.assertIn({"type": "panic", "nick": "boss"}, seen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
