"""Small hardening of the haze desktop app (audit H9–H13).

    python -m unittest discover -s tests
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import stat
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

import aiohttp  # noqa: E402

from haze.network.server import ChatServer  # noqa: E402
from haze.network import web_server  # noqa: E402


def _mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


class WebPageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.renewed = 0

        def renew():
            self.renewed += 1
        self.chat = ChatServer("host", 0, lambda e: None)
        port = 0
        self.web = web_server.WebChatServer("host", port, self.chat, lambda e: None,
                                            asyncio.get_running_loop(), renew_circuit_cb=renew)
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.web._http_port = s.getsockname()[1]
        await self.web.start()
        self.base = f"http://127.0.0.1:{self.web._http_port}"

    async def asyncTearDown(self):
        await self.web.stop()

    async def test_renew_is_not_an_open_endpoint(self):
        """H9: anyone with the onion address could make the host rotate circuits."""
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{self.base}/api/renew") as r:
                self.assertNotEqual(r.status, 200)
        self.assertEqual(self.renewed, 0)

    async def test_renew_is_rate_limited(self):
        self.assertTrue(self.web._renew())
        self.assertFalse(self.web._renew(), "a second renewal right away")
        self.assertEqual(self.renewed, 1)

    async def test_page_headers(self):
        """H10: a policy naming the page's own script and style, and no framing."""
        async with aiohttp.ClientSession() as s:
            async with s.get(self.base + "/") as r:
                html = await r.text()
                h = r.headers
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertEqual(h["Referrer-Policy"], "no-referrer")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        csp = h["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        for tag in ("script", "style"):
            bodies = re.findall(rf"<{tag}>(.*?)</{tag}>", html, re.S)
            self.assertTrue(bodies)
            for body in bodies:
                digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
                self.assertIn(f"'sha256-{digest}'", csp, tag)
        self.assertNotIn("/api/renew", html, "the page still calls the old endpoint")


class LogFileTests(unittest.TestCase):
    def test_no_shared_fallback(self):
        """H11: /tmp/haze.log was the fallback when the state dir could not be made."""
        from haze import logging_setup
        blocker = Path(_HOME, "file-not-dir")
        blocker.write_text("x")
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = str(blocker)
        try:
            self.assertIsNone(logging_setup._default_log_path())
        finally:
            os.environ["XDG_STATE_HOME"] = old
        d = logging_setup._default_log_path().parent
        self.assertEqual(_mode(d), 0o700)


class MediaDirTests(unittest.TestCase):
    def test_private_runtime_dir_and_stale_ones_go(self):
        """H12: received audio/video went to /tmp and outlived a crash."""
        from haze.ui import main_window as mw
        rt = tempfile.mkdtemp(prefix="rt-")
        os.environ["XDG_RUNTIME_DIR"] = rt
        stale = Path(rt, "haze-media", "999999999")
        stale.mkdir(parents=True)
        (stale / "video_x.mp4").write_bytes(b"old")
        mw._MEDIA_DIR = None
        d = mw._media_dir()
        self.assertTrue(d.startswith(rt))
        self.assertEqual(_mode(d), 0o700)
        self.assertEqual(_mode(os.path.dirname(d)), 0o700)
        self.assertFalse(stale.exists(), "a dead run's media was kept")
        Path(d, "audio_1.ogg").write_bytes(b"x")
        mw._cleanup_audio_tmp_files()
        self.assertFalse(os.path.exists(d))

    def test_received_media_is_not_decoded_until_played(self):
        from PyQt6.QtWidgets import QApplication
        from haze.ui import main_window as mw
        QApplication.instance() or QApplication([])
        os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="rt-")
        mw._MEDIA_DIR = None
        msg = mw.FileMessage.__new__(mw.FileMessage)
        calls = []

        class _Btn:
            def setEnabled(self, v):
                calls.append(("enabled", v))
        msg._play_btn = _Btn()
        msg._mime = "audio/ogg"
        msg._audio_player = None
        mw.FileMessage._setup_audio(msg, b"OggS-not-really")
        self.assertIn(("enabled", True), calls)
        self.assertIsNone(msg._audio_player, "the decoder was started before ▶")
        self.assertTrue(msg._audio_tmp_path.startswith(os.environ["XDG_RUNTIME_DIR"]))


class VaultFileTests(unittest.TestCase):
    def test_vault_files_are_owner_only(self):
        """H13: .salt and .hzv were written with the default umask."""
        from haze.storage import vault
        old = os.umask(0o022)
        try:
            vault.save_session("pw", "s", [], [])
        finally:
            os.umask(old)
        self.assertEqual(_mode(vault._VAULT_DIR), 0o700)
        for f in vault._VAULT_DIR.iterdir():
            self.assertEqual(_mode(f), 0o600, f.name)
        self.assertEqual(len(vault.list_sessions()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
