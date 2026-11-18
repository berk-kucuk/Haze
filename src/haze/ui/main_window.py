import asyncio
import base64
import io
import math
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QScrollArea, QSplitter, QFrame, QMessageBox, QApplication,
    QGraphicsOpacityEffect, QSizePolicy, QStyledItemDelegate, QStyle,
    QGraphicsBlurEffect,
    QMenu, QDialog, QCheckBox, QStyleOptionButton, QFileDialog, QInputDialog, QStackedWidget,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QObject, QPropertyAnimation, QPoint, QPointF,
    QEasingCurve, QTimer, QParallelAnimationGroup, QRect, QSize, QRectF,
    QThread, QBuffer, QByteArray, QUrl,
)
from PyQt6.QtGui import (
    QIcon, QCloseEvent, QPixmap, QPainter, QLinearGradient,
    QRadialGradient, QColor, QPen, QBrush, QFont, QKeySequence, QShortcut, QImage,
    QPainterPath, QRegion, QMovie,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from ..tor.controller import TorController
from .popup import WINDOW_RADIUS, _blur_pixmap, _clip_to_window_corners, _Popup
from .tor_connection import TorConnectionWidget
from ..network.server import ChatServer
from ..network.client import ChatClient
from ..secure.memory import full_wipe
from ..assets import LOGO_PATH, WORDMARK, LOGO_TRANSPARENT
from ..i18n import t
from ..storage import settings as _app_settings
from ..storage import vault as _app_vault
from ..storage.vault import (
    check_lock, check_decoy, make_lock_hash, make_decoy_hash, is_legacy_hash,
)
from ..logging_setup import get_logger, wipe_logs
from .tray import build_tray
from .styles import DARK_QSS, THEMES

log = get_logger("ui")

# File-transfer limits live with the protocol now, so the UI, the chat server
# and the web bridge all enforce the same numbers.
from ..network.protocol import MAX_FILE_BYTES, MAX_FILE_CHUNKS  # noqa: E402
# In-flight transfers held per session. Each one buys the sender a reassembly
# buffer and a widget in the receiver's window, so an unbounded count is a way
# to exhaust a peer's memory without ever finishing a transfer.
MAX_INFLIGHT_TRANSFERS = 16


def _plain(label: "QLabel") -> "QLabel":
    """Show the label's text exactly as written.

    QLabel's default, Qt.AutoText, renders anything that looks like HTML as
    HTML. For text a peer controls — messages, nicks, file names — that let any
    participant send styled text, links, local images (<img src="/…">) or a
    fake system line ("⚠ host pressed panic…") that looked like Haze's own.
    """
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _notification_safe(text: str) -> str:
    """Desktop notifications (KDE's included) render a little HTML in the body.
    Swap the markup characters for look-alikes rather than escaping them: a
    server without markup support would show "&lt;" literally."""
    return text.replace("&", "＆").replace("<", "‹").replace(">", "›")

# Extensions QMediaPlayer's backend needs to reliably identify audio
# attachments played straight from a temp file (mirrors mobile's mime-based
# handling — see FileMessage._setup_audio below).
_AUDIO_EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".weba",
}

# Same idea for video attachments played inline (FileMessage._setup_video).
_VIDEO_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/3gpp": ".3gp",
    "video/mpeg": ".mpeg",
    "video/x-msvideo": ".avi",
    "video/ogg": ".ogv",
}

# Temp files created for inline audio/video playback (see FileMessage's
# _setup_audio / _setup_video). Qt object destructors aren't guaranteed to run
# before the panic path's os._exit(0), so these are purged explicitly at
# panic/quit time instead of relying on per-widget cleanup.
_AUDIO_TMP_PATHS: "set[str]" = set()


def _find_tor_browser() -> list[str] | None:
    """Locate a Tor Browser launcher, returning the argv prefix to run it with.

    Checked in order of specificity: an extracted Tor Browser Bundle (what
    torbrowser-launcher installs, and what most users actually have), then
    distro wrappers on PATH, then Flatpak. Returns None when nothing is found,
    in which case the caller falls back to copying the URL.
    """
    bundles = [
        Path.home() / ".local/share/torbrowser/tbb/x86_64/tor-browser/Browser/start-tor-browser",
        Path("/opt/tor-browser/Browser/start-tor-browser"),
        Path("/usr/local/share/tor-browser/Browser/start-tor-browser"),
    ]
    for p in bundles:
        if p.is_file() and os.access(p, os.X_OK):
            return [str(p)]
    for exe in ("tor-browser", "torbrowser-launcher"):
        found = shutil.which(exe)
        if found:
            return [found]
    flatpak = shutil.which("flatpak")
    if flatpak:
        app_id = "com.github.micahflee.torbrowser_launcher"
        try:
            listed = subprocess.run(
                [flatpak, "info", app_id],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
            if listed.returncode == 0:
                return [flatpak, "run", app_id]
        except Exception:
            pass
    return None


_MEDIA_DIR: "str | None" = None


def _media_dir() -> str:
    """Where received audio/video waits for the player (audit H12).

    It used to be /tmp: on disk on many systems, shared by every account, and
    left behind when Haze crashed before the purge. Now: a directory of this
    process's own under $XDG_RUNTIME_DIR — memory-backed, owner-only, emptied
    by the system at logout — and directories of earlier runs that died
    without cleaning up are removed at the next start.
    """
    global _MEDIA_DIR
    if _MEDIA_DIR and os.path.isdir(_MEDIA_DIR):
        return _MEDIA_DIR
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    base = os.path.join(runtime, "haze-media") if runtime else ""
    try:
        if not base:
            raise OSError("no runtime dir")
        os.makedirs(base, mode=0o700, exist_ok=True)
        st = os.lstat(base)
        import stat as _stat
        if not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise OSError("not ours")
        os.chmod(base, 0o700)
        _purge_stale_media(base)
        mine = os.path.join(base, str(os.getpid()))
        os.makedirs(mine, mode=0o700, exist_ok=True)
        _MEDIA_DIR = mine
    except OSError:
        # Still private (mkdtemp is 0700), just not memory-backed.
        _MEDIA_DIR = tempfile.mkdtemp(prefix="haze-media-")
    return _MEDIA_DIR


def _purge_stale_media(base: str) -> None:
    """Remove the media directories of Haze processes that are gone."""
    for name in os.listdir(base):
        if not name.isdigit() or int(name) == os.getpid():
            continue
        if os.path.exists(f"/proc/{name}"):
            continue
        shutil.rmtree(os.path.join(base, name), ignore_errors=True)


def _cleanup_audio_tmp_files() -> None:
    for path in list(_AUDIO_TMP_PATHS):
        try:
            os.remove(path)
        except OSError:
            pass
        _AUDIO_TMP_PATHS.discard(path)
    if _MEDIA_DIR:
        shutil.rmtree(_MEDIA_DIR, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────
# Network bridge (unchanged)
# ──────────────────────────────────────────────────────────────────────

class _NetBridge(QObject):
    event_received = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._server: ChatServer | None = None
        self._client: ChatClient | None = None
        self._web_server = None   # WebChatServer | None, imported lazily

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _emit(self, event: dict) -> None:
        self.event_received.emit(event)
        if self._web_server is not None:
            asyncio.run_coroutine_threadsafe(
                self._web_server.broadcast_event(event), self._loop
            )

    def _qt_only_emit(self, event: dict) -> None:
        """Signal Qt without triggering web broadcast (used for web-originated join/leave)."""
        self.event_received.emit(event)

    def start_server(self, nick: str, local_port: int, http_port: int,
                     renew_circuit_cb=None, session_password: str = "",
                     onion_address: str = "") -> None:
        from ..network.web_server import WebChatServer
        self._server = ChatServer(nick, local_port, self._emit,
                                  session_password=session_password,
                                  onion_address=onion_address)
        asyncio.run_coroutine_threadsafe(self._server.start(), self._loop)
        self._web_server = WebChatServer(
            nick, http_port, self._server, self._qt_only_emit, self._loop,
            renew_circuit_cb=renew_circuit_cb,
            session_password=session_password,
        )
        asyncio.run_coroutine_threadsafe(self._web_server.start(), self._loop)

    def start_client(self, nick: str, onion_host: str, socks_port: int,
                     session_password: str = "") -> None:
        self._client = ChatClient(nick, onion_host, socks_port, self._emit,
                                  session_password=session_password)
        asyncio.run_coroutine_threadsafe(self._client.connect(), self._loop)

    def send_chat(self, content: str, msg_id: str | None = None,
                  reply_to_nick: str | None = None, reply_to_content: str | None = None,
                  disappear_secs: int = 0) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(
                self._server.send_chat(content, msg_id, reply_to_nick, reply_to_content, disappear_secs), self._loop)
        elif self._client:
            asyncio.run_coroutine_threadsafe(
                self._client.send_chat(content, msg_id, reply_to_nick, reply_to_content, disappear_secs), self._loop)

    def send_panic(self) -> None:
        futs = []
        if self._server:
            futs.append(asyncio.run_coroutine_threadsafe(self._server.send_panic(), self._loop))
        elif self._client:
            futs.append(asyncio.run_coroutine_threadsafe(self._client.send_panic(), self._loop))
        for f in futs:
            try:
                f.result(timeout=2.0)
            except Exception:
                pass

    def send_file(self, file_id: str, filename: str, mime: str, data: bytes) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(
                self._server.send_file(file_id, filename, mime, data), self._loop
            )
        elif self._client:
            asyncio.run_coroutine_threadsafe(
                self._client.send_file(file_id, filename, mime, data), self._loop
            )

    def kick_client(self, nick: str) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(
                self._server.kick_client(nick), self._loop
            )

    def send_typing(self, is_typing: bool) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(self._server.send_typing(is_typing), self._loop)
        elif self._client:
            asyncio.run_coroutine_threadsafe(self._client.send_typing(is_typing), self._loop)

    def send_delete(self, msg_id: str) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(self._server.send_delete(msg_id), self._loop)
        elif self._client:
            asyncio.run_coroutine_threadsafe(self._client.send_delete(msg_id), self._loop)

    def send_edit(self, msg_id: str, content: str) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(self._server.send_edit(msg_id, content), self._loop)
        elif self._client:
            asyncio.run_coroutine_threadsafe(self._client.send_edit(msg_id, content), self._loop)

    def send_ping(self, ts: float) -> None:
        if self._client:
            asyncio.run_coroutine_threadsafe(self._client.send_ping(ts), self._loop)

    def stop(self) -> None:
        futs = []
        if self._web_server:
            futs.append(asyncio.run_coroutine_threadsafe(self._web_server.stop(), self._loop))
        if self._server:
            futs.append(asyncio.run_coroutine_threadsafe(self._server.stop(), self._loop))
        if self._client:
            futs.append(asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop))
        for f in futs:
            try:
                f.result(timeout=3.0)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)


# ──────────────────────────────────────────────────────────────────────
# Per-session state container
# ──────────────────────────────────────────────────────────────────────

class ChatSession:
    """Holds all network + UI state for one active chat connection."""

    def __init__(
        self,
        mode: str,
        nick: str,
        onion_url: str = "",
        local_port: int = 0,
        http_port: int = 0,
        service_id: str | None = None,
        session_password: str = "",
    ) -> None:
        self.mode = mode
        self.nick = nick
        self.onion_url = onion_url
        self.local_port = local_port
        self.http_port = http_port
        self.service_id = service_id
        self.session_password = session_password

        self.bridge = _NetBridge()
        self.messages: list = []
        self.file_buffers: dict[str, dict] = {}
        self.users: list[str] = []
        self.auto_scroll = False
        self.connected = False
        self._handshake_done = False
        self._reconnect_banner: "QWidget | None" = None

        # UI widget references — set when the session's content is built
        self.content_widget: QWidget | None = None
        self.user_list: "QListWidget | None" = None
        self.count_label: "QLabel | None" = None
        self.msg_layout: "QVBoxLayout | None" = None
        self.msg_input: "QLineEdit | None" = None
        self.scroll: "QScrollArea | None" = None
        self.tab_btn: "QPushButton | None" = None
        self.typing_bar: "QWidget | None" = None
        self.search_bar: "QWidget | None" = None
        # Join mode: the host's nick — first in the userlist the host sends
        # on joining. Only the host's panic ends the session here.
        self.host_nick: str | None = None
        # msg_id → MessageBubble, for delete/edit
        self.msg_widgets: "dict[str, QWidget]" = {}
        # msg_id → nick of its author, for the whole session (kept after the
        # message disappears, so an id is never handed to anyone else). Only
        # that author's delete/edit is applied; the host stamps every event's
        # nick with the sender's own, and never reuses a nick in a session.
        self.msg_owners: "dict[str, str]" = {}
        # latency ping state
        self.ping_sent_at: float = 0.0
        # slogan overlay reference for fade-out
        self.slogan_widget: "QWidget | None" = None
        self.reply_bar: "QWidget | None" = None
        self._reply_to: "dict | None" = None

    @property
    def label(self) -> str:
        mode_str = "HOST" if self.mode == "host" else "JOIN"
        return f"{mode_str}  ·  {self.nick}"


# ──────────────────────────────────────────────────────────────────────
# Background worker: create a new Tor hidden service
# ──────────────────────────────────────────────────────────────────────

class _SessionCreatorThread(QThread):
    success = pyqtSignal(str, str, int, int)   # onion, service_id, local_port, http_port
    failure = pyqtSignal(str)

    def __init__(self, tor: "TorController") -> None:
        super().__init__()
        self._tor = tor

    def run(self) -> None:
        import random as _random
        local_port = _random.randint(50000, 59999)
        http_port = _random.randint(50000, 59999)
        while http_port == local_port:
            http_port = _random.randint(50000, 59999)
        try:
            onion, service_id = self._tor.create_additional_hidden_service(local_port, http_port)
            self.success.emit(onion, service_id, local_port, http_port)
        except Exception as exc:
            self.failure.emit(str(exc))


# ──────────────────────────────────────────────────────────────────────
# Session tab bar
# ──────────────────────────────────────────────────────────────────────

class _SessionTabBar(QWidget):
    _EXPANDED_W = 158
    _COLLAPSED_W = 34

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setObjectName("sessionSidebar")
        self._collapsed = False

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(5, 8, 5, 8)
        self._lay.setSpacing(3)

        # index 0 — collapse toggle, always visible
        self._collapse_btn = QPushButton("‹")
        self._collapse_btn.setObjectName("sidebarCollapseBtn")
        self._collapse_btn.setFixedHeight(24)
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.clicked.connect(lambda _=False: self._toggle_collapse())
        self._lay.addWidget(self._collapse_btn)

        # index 1 — add-session button
        self._add_btn = QPushButton("＋  " + t("new_session"))
        self._add_btn.setObjectName("addSessionBtn")
        self._add_btn.setFixedHeight(32)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lay.addWidget(self._add_btn)

        # index 2 — separator
        self._sep = QWidget()
        self._sep.setFixedHeight(1)
        self._sep.setStyleSheet("background: rgba(28,28,34,255);")
        self._lay.addWidget(self._sep)

        # session tab buttons are inserted before the trailing stretch
        self._lay.addStretch()

        # Leave session button (always visible at bottom)
        self._leave_btn = QPushButton(t("disconnect"))
        self._leave_btn.setObjectName("leaveBtn")
        self._leave_btn.setFixedHeight(34)
        self._leave_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lay.addWidget(self._leave_btn)

        self.setFixedWidth(self._EXPANDED_W)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        for i in range(1, self._lay.count()):
            item = self._lay.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(not self._collapsed)
        if self._collapsed:
            self.setFixedWidth(self._COLLAPSED_W)
            self._collapse_btn.setText("›")
        else:
            self.setFixedWidth(self._EXPANDED_W)
            self._collapse_btn.setText("‹")

    def add_tab(self, session: ChatSession, on_click) -> None:
        btn = QPushButton(session.label)
        btn.setObjectName("sessionTab")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _=False, cb=on_click: cb())
        self._lay.insertWidget(self._lay.count() - 1, btn)
        if self._collapsed:
            btn.hide()
        session.tab_btn = btn

    def set_active(self, session: ChatSession) -> None:
        for i in range(self._lay.count()):
            item = self._lay.itemAt(i)
            if not (item and item.widget()):
                continue
            w = item.widget()
            if not isinstance(w, QPushButton) or w is self._add_btn or w is self._collapse_btn:
                continue
            w.setObjectName("sessionTabActive" if w is session.tab_btn else "sessionTab")
            w.setStyle(w.style())

    def remove_tab(self, session: ChatSession) -> None:
        if session.tab_btn:
            self._lay.removeWidget(session.tab_btn)
            session.tab_btn.deleteLater()
            session.tab_btn = None

    def update_label(self, session: ChatSession) -> None:
        if session.tab_btn:
            session.tab_btn.setText(session.label)


# ──────────────────────────────────────────────────────────────────────
# Ambient light — animated radial glow background
# ──────────────────────────────────────────────────────────────────────

class _AmbientLight(QWidget):
    """
    Slowly drifting soft radial glows.
    Background is theme-aware: dark for haze/hacker, light for light theme.
    """
    _theme_id: str = "haze"  # set by MainWindow._apply_theme

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._t = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(40)  # 25 fps

    def _step(self) -> None:
        self._t += 0.007
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        tid = self._theme_id

        if tid == "light":
            p.fillRect(self.rect(), QColor(0xf0, 0xf0, 0xf4))
            cx1 = w * (0.5 + 0.38 * math.sin(self._t * 0.32))
            cy1 = h * (0.38 + 0.22 * math.cos(self._t * 0.25))
            g1 = QRadialGradient(cx1, cy1, w * 0.60)
            g1.setColorAt(0.0,  QColor(195, 200, 215, 14))
            g1.setColorAt(0.5,  QColor(215, 218, 228, 6))
            g1.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g1)

        elif tid == "hacker":
            p.fillRect(self.rect(), QColor(0, 0, 0))
            cx1 = w * (0.5 + 0.38 * math.sin(self._t * 0.32))
            cy1 = h * (0.38 + 0.22 * math.cos(self._t * 0.25))
            g1 = QRadialGradient(cx1, cy1, w * 0.62)
            g1.setColorAt(0.0,  QColor(0, 255, 65, 14))
            g1.setColorAt(0.35, QColor(0, 200, 50, 5))
            g1.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g1)
            cx2 = w * (0.5 - 0.32 * math.cos(self._t * 0.21))
            cy2 = h * (0.65 + 0.20 * math.sin(self._t * 0.28))
            g2 = QRadialGradient(cx2, cy2, w * 0.48)
            g2.setColorAt(0.0,  QColor(0, 180, 40, 8))
            g2.setColorAt(0.5,  QColor(0, 140, 30, 3))
            g2.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g2)

        else:
            # haze default: pure black + white glows
            p.fillRect(self.rect(), QColor(0, 0, 0))
            cx1 = w * (0.5 + 0.38 * math.sin(self._t * 0.32))
            cy1 = h * (0.38 + 0.22 * math.cos(self._t * 0.25))
            g1 = QRadialGradient(cx1, cy1, w * 0.62)
            g1.setColorAt(0.0,  QColor(255, 255, 255, 18))
            g1.setColorAt(0.35, QColor(210, 215, 225, 7))
            g1.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g1)
            cx2 = w * (0.5 - 0.32 * math.cos(self._t * 0.21))
            cy2 = h * (0.65 + 0.20 * math.sin(self._t * 0.28))
            g2 = QRadialGradient(cx2, cy2, w * 0.48)
            g2.setColorAt(0.0,  QColor(190, 195, 210, 10))
            g2.setColorAt(0.5,  QColor(150, 155, 170, 4))
            g2.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g2)
            pulse = 0.5 + 0.5 * math.sin(self._t * 0.15)
            g3 = QRadialGradient(w * 0.5, h * 0.5, w * 0.5)
            g3.setColorAt(0.0,  QColor(255, 255, 255, int(6 * pulse)))
            g3.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g3)


# ──────────────────────────────────────────────────────────────────────
# Themed checkbox — draws a visible checkmark via QPainter
# ──────────────────────────────────────────────────────────────────────

class _CheckBox(QCheckBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.isChecked():
            return
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        rect = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, opt, self
        )
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#00ff41") if _AmbientLight._theme_id == "hacker" else QColor("#1a1a1a")
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        x = rect.x() + 3
        y = rect.y() + 3
        w = rect.width() - 6
        h = rect.height() - 6
        p.drawLine(QPointF(x + w * 0.05, y + h * 0.50),
                   QPointF(x + w * 0.38, y + h * 0.80))
        p.drawLine(QPointF(x + w * 0.38, y + h * 0.80),
                   QPointF(x + w * 0.92, y + h * 0.12))


# ──────────────────────────────────────────────────────────────────────
# Chat panel — contains ambient light + scroll area + input bar
# ──────────────────────────────────────────────────────────────────────

class _ChatPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(False)

        self._bg = _AmbientLight(self)
        self._bg.lower()

        # Layout manages scroll area + input bar on top of the bg
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

    def add_scroll(self, scroll: QWidget) -> None:
        self._lay.addWidget(scroll, stretch=1)

    def add_input(self, bar: QWidget) -> None:
        self._lay.addWidget(bar, stretch=0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.lower()


# ──────────────────────────────────────────────────────────────────────
# Custom title bar
# ──────────────────────────────────────────────────────────────────────

class _TitleBar(QWidget):
    """
    Frameless title bar.  Drag is handled by QWindow.startSystemMove()
    which is reliable on both X11 and Wayland.
    """

    def __init__(self, main_win: "MainWindow") -> None:
        super().__init__(main_win)
        self._win = main_win
        self.setObjectName("titleBar")
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.SizeAllCursor)  # visual hint for drag

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(8)

        _vc = Qt.AlignmentFlag.AlignVCenter

        # Wordmark logo
        logo = QLabel()
        logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if WORDMARK.exists():
            px = QPixmap(str(WORDMARK)).scaledToHeight(
                64, Qt.TransformationMode.SmoothTransformation
            )
            logo.setPixmap(px)
        else:
            logo.setText("HAZE")
            logo.setStyleSheet(
                "font-size:15px;font-weight:800;color:#ffffff;letter-spacing:5px;"
            )
        lay.addWidget(logo, 0, _vc)
        lay.addWidget(maze_linux_tag(t("for_maze_linux")), 0, _vc)
        lay.addSpacing(8)

        # Protocol badge — clickable, opens info popup
        self._badge = QPushButton(t("protocol_active"))
        self._badge.setObjectName("protocolBadgeActive")
        self._badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._badge.clicked.connect(main_win._show_protocol_info)
        lay.addWidget(self._badge, 0, _vc)

        lay.addStretch()

        # Latency dot + ms label
        self._latency_dot = _LatencyDot()
        lay.addWidget(self._latency_dot, 0, _vc)
        self._latency_lbl = QLabel("")
        self._latency_lbl.setStyleSheet(
            "font-size:9px;color:#555555;background:transparent;"
        )
        lay.addWidget(self._latency_lbl, 0, _vc)
        lay.addSpacing(6)

        # Onion label (clickable → QR popup) + copy button
        self._onion_lbl = QPushButton("—")
        self._onion_lbl.setObjectName("onionLabel")
        self._onion_lbl.setFixedHeight(24)
        self._onion_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._onion_lbl.clicked.connect(lambda _=False: main_win._show_qr())
        lay.addWidget(self._onion_lbl, 0, _vc)

        self._copy_btn = QPushButton(t("copy"))
        self._copy_btn.setObjectName("copyBtn")
        self._copy_btn.setFixedHeight(24)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(lambda _=False: main_win._copy_onion())
        lay.addWidget(self._copy_btn, 0, _vc)

        # Open the session's web UI in Tor Browser (host mode only — the onion
        # maps virtual port 80 to the built-in web server).
        self._tb_btn = QPushButton(t("open_in_tor_browser"))
        self._tb_btn.setObjectName("copyBtn")
        self._tb_btn.setFixedHeight(24)
        self._tb_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tb_btn.setToolTip(t("open_in_tor_browser_hint"))
        self._tb_btn.clicked.connect(lambda _=False: main_win._open_in_tor_browser())
        lay.addWidget(self._tb_btn, 0, _vc)
        lay.addSpacing(4)

        self._onion_lbl.hide()
        self._copy_btn.hide()
        self._tb_btn.hide()
        self._latency_dot.hide()
        self._latency_lbl.hide()

        # Renew circuit
        self._renew_btn = QPushButton("⟳  Circuit")
        self._renew_btn.setObjectName("copyBtn")
        self._renew_btn.setFixedHeight(24)
        self._renew_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._renew_btn.setToolTip("Rotate Tor circuits without dropping active sessions")
        self._renew_btn.clicked.connect(lambda _=False: main_win._renew_circuit())
        lay.addWidget(self._renew_btn, 0, _vc)
        self._renew_btn.hide()

        # Panic
        panic_btn = QPushButton(t("panic"))
        panic_btn.setObjectName("panicBtn")
        panic_btn.setFixedHeight(24)
        panic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        panic_btn.clicked.connect(main_win._trigger_panic)
        lay.addWidget(panic_btn, 0, _vc)

        # Settings gear
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("settingsBtn")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip(t("settings"))
        settings_btn.clicked.connect(main_win._open_settings)
        lay.addWidget(settings_btn, 0, _vc)

        lay.addSpacing(8)

        # Window controls
        for label, obj, cb in (
            ("−", "winBtn",      main_win.showMinimized),
            ("⊡", "winBtn",      self._toggle_max),
            ("✕", "winBtnClose", main_win._close_to_tray),
        ):
            b = QPushButton(label)
            b.setObjectName(obj)
            b.setFixedSize(26, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(cb)
            lay.addWidget(b, 0, _vc)
        lay.addSpacing(2)

    # ── Drag via system move ──────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._win.windowHandle()
            if handle:
                handle.startSystemMove()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()

    def _toggle_max(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def update_for_session(self, session: "ChatSession") -> None:
        if session.mode == "host":
            addr = (session.onion_url or "—").removesuffix(".onion")
            self._onion_lbl.setText(addr)
            self._onion_lbl.show()
            self._copy_btn.show()
            # Only meaningful once the onion is actually published.
            self._tb_btn.setVisible(bool(session.onion_url))
            self._latency_dot.hide()
            self._latency_lbl.hide()
        else:
            self._onion_lbl.hide()
            self._copy_btn.hide()
            self._tb_btn.hide()
            self._latency_dot.show()
            self._latency_lbl.show()
            self._latency_dot.set_latency(None)
            self._latency_lbl.setText("")
        self._renew_btn.show()

    def set_badge(self, text: str, active: bool) -> None:
        self._badge.setText(text)
        self._badge.setObjectName("protocolBadgeActive" if active else "protocolBadge")
        self._badge.setStyle(self._badge.style())


# ──────────────────────────────────────────────────────────────────────
# Avatar delegate for user list
# ──────────────────────────────────────────────────────────────────────

class _AvatarDelegate(QStyledItemDelegate):
    _R = 11

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 44)

    def paint(self, painter, option, index) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect

        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hov = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if is_sel or is_hov:
            bg = QColor(255, 255, 255, 8 if is_sel else 4)
            r = rect.adjusted(6, 2, -6, -2)
            painter.setBrush(QBrush(bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(r, 8, 8)

        nick = index.data(Qt.ItemDataRole.UserRole) or ""
        initial = nick[:1].upper() if nick else "?"
        cx = rect.left() + 20
        cy = rect.center().y()
        r = self._R

        painter.setBrush(QBrush(QColor(24, 24, 26)))
        painter.setPen(QPen(QColor(45, 45, 48), 1))
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        f = QFont("Inter"); f.setPixelSize(9); f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(100, 100, 105))
        painter.drawText(QRect(cx - r, cy - r, r * 2, r * 2),
                         Qt.AlignmentFlag.AlignCenter, initial)

        # Online dot
        painter.setBrush(QBrush(QColor("#34c759")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx + r - 4, cy + r - 5, 6, 6)

        display = index.data(Qt.ItemDataRole.DisplayRole) or ""
        tr = QRect(rect.left() + 40, rect.top(), rect.width() - 50, rect.height())
        f2 = QFont("Inter"); f2.setPixelSize(12)
        painter.setFont(f2)
        painter.setPen(QColor("#ffffff" if is_sel else "#c0c0c0"))
        painter.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         display)


# ──────────────────────────────────────────────────────────────────────
# Scroll area with edge fades
# ──────────────────────────────────────────────────────────────────────

class _EdgeFade(QWidget):
    def __init__(self, parent: QWidget, direction: str) -> None:
        super().__init__(parent)
        self._dir = direction
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        if self._dir == "top":
            g.setColorAt(0.0, QColor(0, 0, 0, 200))
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
        else:
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, 140))
        p.fillRect(self.rect(), g)


class _ScrollArea(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._top = _EdgeFade(self, "top")
        self._bot = _EdgeFade(self, "bottom")
        self._top.raise_()
        self._bot.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w = self.width()
        self._top.setGeometry(0, 0, w, 60)
        self._bot.setGeometry(0, self.height() - 36, w, 36)


# ──────────────────────────────────────────────────────────────────────
# Input bar with top-shadow paint
# ──────────────────────────────────────────────────────────────────────

class _InputBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("inputBar")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, 28)
        g.setColorAt(0.0, QColor(0, 0, 0, 80))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, self.width(), 28, g)


# ──────────────────────────────────────────────────────────────────────
# Separator rule
# ──────────────────────────────────────────────────────────────────────

class _HRule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(1)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0.0, QColor(0, 0, 0, 0))
        g.setColorAt(0.4, QColor(35, 35, 38, 200))
        g.setColorAt(0.6, QColor(35, 35, 38, 200))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g)


# ──────────────────────────────────────────────────────────────────────
# Animation helper
# ──────────────────────────────────────────────────────────────────────

def _slide_in(widget: QWidget, duration: int = 320) -> None:
    """Parallel height-expand + fade-in. Stores refs to prevent GC."""
    fx = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(fx)
    fx.setOpacity(0.0)

    op = QPropertyAnimation(fx, b"opacity")
    op.setParent(widget)
    op.setDuration(duration)
    op.setStartValue(0.0)
    op.setEndValue(1.0)
    op.setEasingCurve(QEasingCurve.Type.OutCubic)

    widget.setMaximumHeight(0)
    h = QPropertyAnimation(widget, b"maximumHeight")
    h.setParent(widget)
    h.setDuration(duration)
    h.setStartValue(0)
    h.setEndValue(600)
    h.setEasingCurve(QEasingCurve.Type.OutCubic)
    h.finished.connect(lambda w=widget: w.setMaximumHeight(16_777_215))

    g = QParallelAnimationGroup(widget)
    g.addAnimation(op)
    g.addAnimation(h)
    g.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
    g.start()
    widget._sg = g   # keep alive
    widget._sfx = fx


# ──────────────────────────────────────────────────────────────────────
# Tor circuit visualization widget
# ──────────────────────────────────────────────────────────────────────

class _CircuitWidget(QWidget):
    _NODES = [
        ("YOU",     False),
        ("GUARD",   True),
        ("RELAY",   True),
        ("SERVICE", True),
        ("PEER",    False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(108)
        self.setAutoFillBackground(False)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self) -> None:
        self._t = (self._t + 0.010) % 1.0
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        n = len(self._NODES)
        nw, nh = 62, 26
        pad = nw // 2 + 10   # keep nodes fully inside bounds
        usable = w - 2 * pad
        step = usable / (n - 1)
        cy = h // 2 - 4

        xs = [int(pad + i * step) for i in range(n)]

        # Encryption tunnel glow
        tunnel = QRect(xs[0], cy - nh // 2 - 10, xs[-1] - xs[0], nh + 20)
        g = QLinearGradient(xs[0], 0, xs[-1], 0)
        g.setColorAt(0.0, QColor(52, 199, 89, 0))
        g.setColorAt(0.2, QColor(52, 199, 89, 10))
        g.setColorAt(0.8, QColor(52, 199, 89, 10))
        g.setColorAt(1.0, QColor(52, 199, 89, 0))
        p.fillRect(tunnel, g)

        # Connecting lines (dotted)
        for i in range(n - 1):
            x1 = xs[i] + nw // 2
            x2 = xs[i + 1] - nw // 2
            pen = QPen(QColor(52, 199, 89, 55), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(x1, cy, x2, cy)

            # Arrow chevron at midpoint
            mx = (x1 + x2) // 2
            p.setPen(QPen(QColor(52, 199, 89, 80), 1))
            p.drawLine(mx - 5, cy - 4, mx, cy)
            p.drawLine(mx - 5, cy + 4, mx, cy)

        # Animated data pulse (green dot travelling along path)
        px_pos = xs[0] + self._t * (xs[-1] - xs[0])
        pulse = 0.5 + 0.5 * math.sin(self._t * math.pi * 4)
        r = 3.5 + pulse * 1.5
        alpha = int(160 + 95 * pulse)
        # Glow
        glow = QRadialGradient(px_pos, cy, 14)
        glow.setColorAt(0.0, QColor(52, 199, 89, int(50 * pulse)))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRect(int(px_pos) - 14, cy - 14, 28, 28), glow)
        # Dot
        p.setBrush(QBrush(QColor(52, 199, 89, alpha)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(px_pos - r, cy - r, r * 2, r * 2))

        # Nodes
        for i, (label, is_tor) in enumerate(self._NODES):
            x = xs[i]
            rect = QRect(x - nw // 2, cy - nh // 2, nw, nh)

            if is_tor:
                bg     = QColor(6, 22, 10)
                border = QColor(28, 88, 44)
                tc     = QColor(52, 199, 89)
            else:
                bg     = QColor(16, 16, 20)
                border = QColor(50, 50, 56)
                tc     = QColor(170, 170, 178)

            p.setBrush(QBrush(bg))
            p.setPen(QPen(border, 1))
            p.drawRoundedRect(rect, 7, 7)

            f = QFont("Inter")
            f.setPixelSize(8)
            f.setBold(True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            p.setFont(f)
            p.setPen(tc)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

            # Sub-label below node
            sub_rect = QRect(x - 40, cy + nh // 2 + 5, 80, 12)
            f2 = QFont("Inter")
            f2.setPixelSize(7)
            p.setFont(f2)
            p.setPen(QColor(100, 100, 108))
            sub = ("you", "guard node", "relay node", "hidden svc", "peer")[i]
            p.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, sub)


# ──────────────────────────────────────────────────────────────────────
# Protocol info popup
# ──────────────────────────────────────────────────────────────────────

class _ProtocolPopup(QWidget):
    def __init__(self, main_win: "MainWindow") -> None:
        super().__init__(main_win)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(main_win.rect())

        self._bg = _blur_pixmap(main_win.grab(), radius=32)
        self._panel: QWidget | None = None
        self._build_panel(main_win)
        self.raise_()
        self._fade_in()

    # ── Fade in ─────────────────────────────────────────────────────

    def _fade_in(self) -> None:
        fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(fx)
        fx.setOpacity(0.0)
        a = QPropertyAnimation(fx, b"opacity", self)
        a.setDuration(200)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(lambda: self.setGraphicsEffect(None))
        a.start()
        self._anim = a
        self._fx   = fx

    # ── Background paint ─────────────────────────────────────────────

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _clip_to_window_corners(p, self)
        p.drawPixmap(0, 0, self._bg)
        p.fillRect(self.rect(), QColor(0, 0, 0, 160))

    # ── Close on outside click / Escape ──────────────────────────────

    def mousePressEvent(self, event) -> None:
        if self._panel and not self._panel.geometry().contains(event.pos()):
            self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    # ── Panel build ──────────────────────────────────────────────────

    def _build_panel(self, mw: "MainWindow") -> None:
        pw, ph = 520, 560
        self._panel = QWidget(self)
        self._panel.setObjectName("protocolPanel")
        self._panel.setGeometry(
            (self.width()  - pw) // 2,
            (self.height() - ph) // 2,
            pw, ph,
        )

        lay = QVBoxLayout(self._panel)
        lay.setContentsMargins(32, 26, 32, 26)
        lay.setSpacing(0)

        # ── Header ──
        hdr = QHBoxLayout()
        title = QLabel("⬡  HAZE PROTOCOL")
        title.setObjectName("popupTitle")
        hdr.addWidget(title)
        hdr.addStretch()
        enc_badge = QLabel("E2E ENCRYPTED")
        enc_badge.setObjectName("popupEncBadge")
        hdr.addWidget(enc_badge)
        hdr.addSpacing(10)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("popupCloseBtn")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)
        lay.addSpacing(20)

        # ── Circuit ──
        sep_top = self._hsep()
        lay.addWidget(sep_top)
        lay.addSpacing(18)
        circuit = _CircuitWidget()
        lay.addWidget(circuit)
        lay.addSpacing(18)
        lay.addWidget(self._hsep())
        lay.addSpacing(20)

        # ── Info grid ──
        grid = QVBoxLayout()
        grid.setSpacing(0)

        def section(label: str) -> None:
            lbl = QLabel(label)
            lbl.setObjectName("popupSectionLabel")
            grid.addWidget(lbl)
            grid.addSpacing(8)

        def row(key: str, val: str, val_green: bool = False) -> None:
            r = QHBoxLayout()
            k = QLabel(key)
            k.setObjectName("popupKey")
            v = QLabel(val)
            v.setObjectName("popupValueGreen" if val_green else "popupValue")
            r.addWidget(k)
            r.addStretch()
            r.addWidget(v)
            grid.addLayout(r)
            grid.addSpacing(6)

        section("ENCRYPTION")
        row("Cipher",         "ChaCha20-Poly1305",    True)
        row("Key Exchange",   "X25519 ECDH",           True)
        row("Key Derivation", "HKDF · SHA-256",        True)
        row("Session Keys",   "Ephemeral",              True)
        grid.addSpacing(14)

        section("CONNECTION")
        row("Transport", "Tor Hidden Service")
        active = mw._active
        if active and active.mode == "host" and active.onion_url:
            addr = active.onion_url
            short = addr[:20] + "…" + addr[-6:]
            row("Onion Address", short)
        elif active and active.mode == "join" and active.onion_url:
            addr = active.onion_url
            short = addr[:20] + "…" + addr[-6:] if len(addr) > 28 else addr
            row("Host Onion", short)
        row("Socks Port", str(mw.tor.socks_port) if hasattr(mw.tor, "socks_port") else "—")
        grid.addSpacing(14)

        section("PRIVACY")
        row("Logs",     "None  ·  Zero retention",  True)
        row("Identity", "Anonymous via Tor",         True)
        row("Panic",    "os._exit(0) wipe",          False)

        lay.addLayout(grid)
        lay.addStretch()

    @staticmethod
    def _hsep() -> QWidget:
        w = QWidget()
        w.setFixedHeight(1)
        w.setStyleSheet("background: rgba(45,45,50,200);")
        return w


# ──────────────────────────────────────────────────────────────────────
# Chat message widgets
# ──────────────────────────────────────────────────────────────────────

class _BlurMixin:
    """Privacy blur for messages — click to reveal, re-blurs after 6s."""

    def _init_blur(self) -> None:
        self._blurred = False
        self._blur_capable = False
        self._blur_delay_timer: QTimer | None = None
        self._blur_reveal_timer: QTimer | None = None
        self._bubble.installEventFilter(self)
        for child in self._bubble.findChildren(QWidget):
            child.installEventFilter(self)

    def enable_blur(self, immediate: bool = False) -> None:
        self._blur_capable = True
        if getattr(self, "_deleted", False):
            return
        if immediate:
            self._apply_blur()
        else:
            if self._blur_delay_timer:
                self._blur_delay_timer.stop()
            self._blur_delay_timer = QTimer(self)
            self._blur_delay_timer.setSingleShot(True)
            self._blur_delay_timer.timeout.connect(self._apply_blur)
            self._blur_delay_timer.start(4000)

    def disable_blur(self) -> None:
        self._blur_capable = False
        if self._blur_delay_timer:
            self._blur_delay_timer.stop()
        if self._blur_reveal_timer:
            self._blur_reveal_timer.stop()
        self._remove_blur()

    def _apply_blur(self) -> None:
        try:
            if not self._blur_capable or getattr(self, "_deleted", False):
                return
            self._blurred = True
            # Toggle the "blurred" dynamic property rather than pushing an
            # inline stylesheet: the QSS rule in styles.py
            # (#bubbleMe[blurred="true"], #bubbleOther[blurred="true"]) doesn't
            # override border-radius, so it inherits the same asymmetric
            # per-corner radius the base #bubbleMe/#bubbleOther rules use —
            # which is exactly what _update_mask() below clips to. A hardcoded
            # inline stylesheet here previously used a uniform radius that
            # didn't match the mask's sharp corner, letting the blur leak past
            # the bubble's rendered edge on that corner.
            self._bubble.setProperty("blurred", "true")
            self._bubble.style().unpolish(self._bubble)
            self._bubble.style().polish(self._bubble)
            fx = QGraphicsBlurEffect()
            fx.setBlurRadius(24)
            self._bubble.setGraphicsEffect(fx)
            self._update_mask()
        except Exception:
            pass

    def _update_mask(self) -> None:
        try:
            r = self._bubble.rect()
            if not r.isValid() or r.isEmpty():
                return
            path = QPainterPath()
            tl = 18.0
            tr = 18.0
            br = 4.0 if self._bubble.objectName() == "bubbleMe" else 18.0
            bl = 18.0 if self._bubble.objectName() == "bubbleMe" else 4.0
            w = r.width()
            h = r.height()
            x = r.x()
            y = r.y()
            path.moveTo(x + tl, y)
            path.lineTo(x + w - tr, y)
            path.arcTo(QRectF(x + w - 2 * tr, y, 2 * tr, 2 * tr), 90, -90)
            path.lineTo(x + w, y + h - br)
            path.arcTo(QRectF(x + w - 2 * br, y + h - 2 * br, 2 * br, 2 * br), 0, -90)
            path.lineTo(x + bl, y + h)
            path.arcTo(QRectF(x, y + h - 2 * bl, 2 * bl, 2 * bl), -90, -90)
            path.lineTo(x, y + tl)
            path.arcTo(QRectF(x, y, 2 * tl, 2 * tl), 180, -90)
            path.closeSubpath()
            self._bubble.setMask(QRegion(path.toFillPolygon().toPolygon()))
        except Exception:
            pass

    def _remove_blur(self) -> None:
        try:
            self._blurred = False
            self._bubble.setGraphicsEffect(None)
            self._bubble.clearMask()
            self._bubble.setProperty("blurred", "false")
            self._bubble.style().unpolish(self._bubble)
            self._bubble.style().polish(self._bubble)
        except Exception:
            pass

    def _reveal_on_click(self, event) -> None:
        if self._blurred:
            self._remove_blur()
            if self._blur_reveal_timer:
                self._blur_reveal_timer.stop()
            self._blur_reveal_timer = QTimer(self)
            self._blur_reveal_timer.setSingleShot(True)
            self._blur_reveal_timer.timeout.connect(self._apply_blur)
            self._blur_reveal_timer.start(6000)

    def eventFilter(self, obj, event) -> bool:
        # This is a Qt virtual-method override invoked directly from C++ for
        # every event on every watched bubble/child widget — an exception
        # escaping here (unlike one raised in a plain .connect() slot) can
        # abort the whole application, so never let one propagate.
        try:
            if event.type() == event.Type.MouseButtonPress and self._blurred:
                w = obj
                while w is not None:
                    if w is self._bubble:
                        self._reveal_on_click(event)
                        break
                    w = w.parent()
        except Exception:
            pass
        return False


class MessageBubble(QWidget, _BlurMixin):
    def __init__(
        self,
        nick: str,
        content: str,
        is_me: bool = False,
        msg_id: str = "",
        on_delete=None,
        on_edit=None,
        on_reply=None,
        disappear_secs: int = 0,
        on_disappear=None,
        show_author: bool = True,
        blur_messages: bool = False,
        reply_to_nick: str = "",
        reply_to_content: str = "",
    ) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        self._nick = nick
        self._content = content
        self._is_me = is_me
        self._msg_id = msg_id
        self._on_delete = on_delete
        self._on_edit = on_edit
        self._on_reply = on_reply
        self._deleted = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 3, 20, 3)
        outer.setSpacing(0)

        row = QHBoxLayout()

        self._bubble = QFrame()
        self._bubble.setObjectName("bubbleMe" if is_me else "bubbleOther")
        self._bubble.setAutoFillBackground(False)

        inner = QVBoxLayout(self._bubble)
        inner.setContentsMargins(13, 10, 13, 8)
        inner.setSpacing(3)

        if not is_me and show_author:
            n = _plain(QLabel(nick.upper()))
            n.setObjectName("nickLabel")
            inner.addWidget(n)
        elif is_me and show_author:
            n = QLabel("YOU")
            n.setObjectName("nickLabel")
            n.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            inner.addWidget(n)

        # Reply quote
        if reply_to_nick:
            rq = QFrame()
            rq.setObjectName("replyQuote")
            rq_lay = QVBoxLayout(rq)
            rq_lay.setContentsMargins(8, 4, 8, 4)
            rq_lay.setSpacing(2)
            rn_lbl = QLabel(reply_to_nick.upper())
            rn_lbl.setObjectName("replyNick")
            rn_lbl.setTextFormat(Qt.TextFormat.PlainText)
            preview = reply_to_content[:80] + ("…" if len(reply_to_content) > 80 else "")
            rc_lbl = QLabel(preview)
            rc_lbl.setObjectName("replyContent")
            rc_lbl.setTextFormat(Qt.TextFormat.PlainText)
            rq_lay.addWidget(rn_lbl)
            rq_lay.addWidget(rc_lbl)
            inner.addWidget(rq)

        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._render_content(content)
        inner.addLayout(self._content_layout)

        foot = QHBoxLayout()
        foot.setSpacing(6)
        self._ts_lbl = QLabel(datetime.now().strftime("%H:%M"))
        self._ts_lbl.setObjectName("tsLabel")
        self._ts_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight if is_me else Qt.AlignmentFlag.AlignLeft
        )
        foot.addWidget(self._ts_lbl)

        if disappear_secs > 0:
            mins = disappear_secs // 60
            badge_txt = f"⏱ {mins}m" if mins > 0 else f"⏱ {disappear_secs}s"
            self._disappear_badge = QLabel(badge_txt)
            self._disappear_badge.setStyleSheet(
                "color: #34c759; font-size: 9px; font-weight: 600; background: transparent;"
            )
            foot.addWidget(self._disappear_badge)

        inner.addLayout(foot)

        if is_me:
            row.addStretch()
            row.addWidget(self._bubble)
        else:
            row.addWidget(self._bubble)
            row.addStretch()

        outer.addLayout(row)

        # Context menu
        if msg_id:
            self._bubble.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self._bubble.customContextMenuRequested.connect(self._show_context_menu)
            for child in self._bubble.findChildren(QWidget):
                child.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # Blur support
        self._init_blur()
        if blur_messages:
            self.enable_blur()

        # Disappearing timer
        if disappear_secs > 0 and on_disappear:
            self._disappear_timer = QTimer(self)
            self._disappear_timer.setSingleShot(True)
            self._disappear_timer.timeout.connect(on_disappear)
            self._disappear_timer.start(disappear_secs * 1000)

    def _render_content(self, content: str) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parts = content.split("```")
        for i, part in enumerate(parts):
            if not part:
                continue
            if i % 2 == 1:
                frame = QFrame()
                frame.setObjectName("codeBlock")
                fl = QVBoxLayout(frame)
                fl.setContentsMargins(10, 8, 10, 8)
                lbl = _plain(QLabel(part.strip()))
                lbl.setObjectName("codeText")
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                fl.addWidget(lbl)
                self._content_layout.addWidget(frame)
            else:
                text = part.strip()
                if text:
                    lbl = _plain(QLabel(text))
                    lbl.setObjectName("msgText")
                    lbl.setWordWrap(True)
                    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                    lbl.setMaximumWidth(540)
                    self._content_layout.addWidget(lbl)

    def _show_context_menu(self, pos) -> None:
        if self._deleted:
            return
        menu = QMenu(self)
        if self._on_reply:
            reply_a = menu.addAction(t("reply_message"))
            reply_a.triggered.connect(self._do_reply)
        copy_a = menu.addAction(t("copy_message"))
        copy_a.triggered.connect(self._do_copy)
        if self._is_me and self._on_edit:
            menu.addSeparator()
            edit_a = menu.addAction(t("edit_message"))
            edit_a.triggered.connect(self._do_edit)
        if self._is_me and self._on_delete:
            del_a = menu.addAction(t("delete_message"))
            del_a.triggered.connect(self._do_delete)
        menu.exec(self._bubble.mapToGlobal(pos))

    def _do_reply(self) -> None:
        if self._on_reply:
            self._on_reply(self._nick, self._content)

    def _do_copy(self) -> None:
        QApplication.clipboard().setText(self._content)

    def _do_edit(self) -> None:
        if self._on_edit:
            self._on_edit(self._msg_id, self._content)

    def _do_delete(self) -> None:
        if self._on_delete:
            self._on_delete(self._msg_id)

    def mark_deleted(self) -> None:
        self._deleted = True
        self._content = ""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        lbl = QLabel(t("msg_deleted"))
        lbl.setObjectName("tsLabel")
        lbl.setStyleSheet("color: #333333; font-style: italic;")
        self._content_layout.addWidget(lbl)
        self._bubble.setObjectName("bubbleOther")
        self._bubble.setStyle(self._bubble.style())

    def update_content(self, new_content: str) -> None:
        self._content = new_content
        self._render_content(new_content)
        edited = QLabel(t("msg_edited"))
        edited.setObjectName("tsLabel")
        edited.setStyleSheet("color: #404040; font-style: italic; font-size: 9px;")
        self._content_layout.addWidget(edited)

    def set_highlight(self, on: bool) -> None:
        if on:
            self._bubble.setObjectName("bubbleHighlight")
        else:
            self._bubble.setObjectName("bubbleMe" if self._is_me else "bubbleOther")
        self._bubble.setStyle(self._bubble.style())


class SystemMessage(QWidget):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 10, 28, 10)
        lay.setSpacing(14)
        lay.addWidget(_HRule())
        lbl = _plain(QLabel(text))       # carries peers' nicks
        lbl.setObjectName("systemMsg")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        lay.addWidget(lbl)
        lay.addWidget(_HRule())


class PanicBanner(QWidget):
    def __init__(self, nick: str) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 8)
        frame = QFrame()
        frame.setObjectName("panicBanner")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(16, 14, 16, 14)
        lbl = _plain(QLabel(t("panic_banner").format(nick.upper())))
        lbl.setObjectName("panicBannerText")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.addWidget(lbl)
        lay.addWidget(frame)


class SloganWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        lay.addStretch()

        if WORDMARK.exists():
            logo = QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            px = QPixmap(str(WORDMARK)).scaledToHeight(
                280, Qt.TransformationMode.SmoothTransformation
            )
            logo.setPixmap(px)
            fx = QGraphicsOpacityEffect(logo)
            fx.setOpacity(0.22)
            logo.setGraphicsEffect(fx)
            logo._fx = fx
            lay.addWidget(logo)
            lay.addSpacing(6)

        lbl = QLabel(t("slogan"))
        lbl.setObjectName("sloganText")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)
        lay.addSpacing(2)

        sub = QLabel(t("slogan_sub"))
        sub.setObjectName("sloganSub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)

        lay.addStretch()


# ──────────────────────────────────────────────────────────────────────
# Typing indicator bar
# ──────────────────────────────────────────────────────────────────────

class _TypingBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("typingBar")
        self.setFixedHeight(26)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 4, 24, 4)
        self._lbl = _plain(QLabel(""))  # "<nick> is typing…"
        self._lbl.setObjectName("typingLabel")
        lay.addWidget(self._lbl)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._clear)
        self.hide()

    def set_typing(self, nick: str) -> None:
        self._lbl.setText(t("is_typing").format(nick))
        self.show()
        self._timer.start(5000)

    def _clear(self) -> None:
        self._lbl.setText("")
        self.hide()

    def clear_nick(self, nick: str) -> None:
        if nick in self._lbl.text():
            self._timer.stop()
            self._clear()


# ──────────────────────────────────────────────────────────────────────
# Message search bar
# ──────────────────────────────────────────────────────────────────────

class _SearchBar(QWidget):
    def __init__(self, session: "ChatSession", parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self.setObjectName("searchBar")
        self.setFixedHeight(48)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(6)

        self._input = QLineEdit()
        self._input.setObjectName("searchInput")
        self._input.setPlaceholderText(t("search_placeholder"))
        self._input.textChanged.connect(self._search)
        lay.addWidget(self._input)

        self._counter = QLabel("")
        self._counter.setObjectName("searchCounter")
        lay.addWidget(self._counter)

        prev_btn = QPushButton("↑")
        prev_btn.setObjectName("searchNavBtn")
        prev_btn.clicked.connect(self._prev)
        lay.addWidget(prev_btn)

        next_btn = QPushButton("↓")
        next_btn.setObjectName("searchNavBtn")
        next_btn.clicked.connect(self._next)
        lay.addWidget(next_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("searchCloseBtn")
        close_btn.clicked.connect(self._close_self)
        lay.addWidget(close_btn)

        self._matches: list[MessageBubble] = []
        self._current: int = 0

    def _search(self, text: str) -> None:
        for w in self._matches:
            w.set_highlight(False)
        self._matches = []
        self._current = 0
        if not text:
            self._counter.setText("")
            return
        lay = self._session.msg_layout
        if not lay:
            return
        lo = text.lower()
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if not item or not item.widget():
                continue
            w = item.widget()
            if isinstance(w, MessageBubble) and lo in w._content.lower():
                self._matches.append(w)
        self._update_counter()
        if self._matches:
            self._scroll_to(self._matches[0])
            self._matches[0].set_highlight(True)

    def _update_counter(self) -> None:
        if not self._matches:
            self._counter.setText(t("search_no_results") if self._input.text() else "")
        else:
            self._counter.setText(f"{self._current + 1}/{len(self._matches)}")

    def _scroll_to(self, w: "MessageBubble") -> None:
        if self._session.scroll:
            self._session.scroll.ensureWidgetVisible(w)

    def _prev(self) -> None:
        if not self._matches:
            return
        self._matches[self._current].set_highlight(False)
        self._current = (self._current - 1) % len(self._matches)
        self._matches[self._current].set_highlight(True)
        self._scroll_to(self._matches[self._current])
        self._update_counter()

    def _next(self) -> None:
        if not self._matches:
            return
        self._matches[self._current].set_highlight(False)
        self._current = (self._current + 1) % len(self._matches)
        self._matches[self._current].set_highlight(True)
        self._scroll_to(self._matches[self._current])
        self._update_counter()

    def _close_self(self) -> None:
        for w in self._matches:
            w.set_highlight(False)
        self.hide()
        if self._session.msg_input:
            self._session.msg_input.setFocus()


# ──────────────────────────────────────────────────────────────────────
# Latency dot (title bar widget)
# ──────────────────────────────────────────────────────────────────────

class _LatencyDot(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._color = QColor("#505050")
        self._tooltip_text = t("latency_unknown")

    def set_latency(self, ms: int | None) -> None:
        if ms is None:
            self._color = QColor("#505050")
            self._tooltip_text = t("latency_unknown")
        elif ms < 600:
            self._color = QColor("#34c759")
            self._tooltip_text = f"{t('latency_good')}  ({ms} ms)"
        elif ms < 1800:
            self._color = QColor("#ffd60a")
            self._tooltip_text = f"{t('latency_medium')}  ({ms} ms)"
        else:
            self._color = QColor("#ff3b30")
            self._tooltip_text = f"{t('latency_poor')}  ({ms} ms)"
        self.setToolTip(self._tooltip_text)
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(self.rect())


# ──────────────────────────────────────────────────────────────────────
# Voice record button
# ──────────────────────────────────────────────────────────────────────

class _VoiceButton(QPushButton):
    """Hold to record audio; releases to send."""

    def __init__(self, on_recorded, parent=None) -> None:
        super().__init__("🎙", parent)
        self.setObjectName("voiceBtn")
        self.setFixedSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(t("voice_note"))
        self._on_recorded = on_recorded
        self._recording = False
        self._frames: list = []
        self._stream = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_recording()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._recording:
            self._stop_recording()
        super().mouseReleaseEvent(event)

    def _start_recording(self) -> None:
        try:
            import sounddevice as sd
            self._frames = []
            self._recording = True
            self.setObjectName("voiceBtnRecording")
            self.setStyle(self.style())
            self._stream = sd.InputStream(
                samplerate=16000, channels=1, dtype="int16",
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception:
            self._recording = False

    def _audio_callback(self, indata, frames, ts, status) -> None:
        if self._recording:
            self._frames.append(indata.copy())

    def _stop_recording(self) -> None:
        self._recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.setObjectName("voiceBtn")
        self.setStyle(self.style())
        if not self._frames:
            return
        try:
            import numpy as np
            audio = np.concatenate(self._frames, axis=0)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio.tobytes())
            self._on_recorded(buf.getvalue())
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


# ──────────────────────────────────────────────────────────────────────
# File message bubble
# ──────────────────────────────────────────────────────────────────────

class _ReconnectBanner(QWidget):
    def __init__(self, on_reconnect) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 6, 20, 6)
        bar = QFrame()
        bar.setObjectName("reconnectBanner")
        bar.setStyleSheet(
            "QFrame#reconnectBanner {"
            "  background: rgba(220,38,38,20); border-radius: 10px;"
            "}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(10)
        lbl = QLabel("Connection lost")
        lbl.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 600; background: transparent;")
        lay.addWidget(lbl)
        lay.addStretch()
        btn = QPushButton("Reconnect")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background: #166534; border-radius: 6px; color: #fff;"
            " font-size: 12px; font-weight: 700; padding: 5px 14px; }"
            "QPushButton:hover { background: #15803d; }"
        )
        btn.clicked.connect(on_reconnect)
        lay.addWidget(btn)
        outer.addWidget(bar)


class FileMessage(QWidget, _BlurMixin):
    def __init__(self, nick: str, filename: str, total_size: int,
                 mime: str, is_me: bool = False, blur_messages: bool = False,
                 show_author: bool = True) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        self._filename = filename
        self._mime = mime
        self._data: bytes | None = None
        self._deleted = False
        self._is_me = is_me
        self._gif_movie: QMovie | None = None
        self._gif_buffer: QBuffer | None = None
        self._gif_bytes: QByteArray | None = None
        # One player drives both inline audio and inline video; only the mime
        # decides whether a video surface is attached to it.
        self._audio_player: QMediaPlayer | None = None
        self._audio_output: QAudioOutput | None = None
        self._audio_tmp_path: str | None = None
        self._video_widget: QVideoWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 3, 20, 3)

        row = QHBoxLayout()
        self._bubble = QFrame()
        self._bubble.setObjectName("bubbleMe" if is_me else "bubbleOther")
        self._bubble.setAutoFillBackground(False)

        inner = QVBoxLayout(self._bubble)
        inner.setContentsMargins(13, 10, 13, 8)
        inner.setSpacing(5)

        if not is_me and show_author:
            n = _plain(QLabel(nick.upper()))
            n.setObjectName("nickLabel")
            inner.addWidget(n)
        elif is_me and show_author:
            n = QLabel("YOU")
            n.setObjectName("nickLabel")
            n.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            inner.addWidget(n)

        # Icon + info row
        info_row = QHBoxLayout()
        if mime.startswith("image/"):
            icon = "🖼"
        elif mime.startswith("audio/"):
            icon = "🎵"
        elif mime.startswith("video/"):
            icon = "🎬"
        else:
            icon = "📎"
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 20px; background: transparent;")
        icon_lbl.setFixedWidth(28)
        info_row.addWidget(icon_lbl)

        meta = QVBoxLayout()
        name_lbl = _plain(QLabel(filename))
        name_lbl.setStyleSheet(
            "color: #eeeeee; font-size: 12px; font-weight: bold; background: transparent;"
        )
        name_lbl.setMaximumWidth(340)
        size_lbl = QLabel(_format_size(total_size))
        size_lbl.setStyleSheet("color: #686868; font-size: 10px; background: transparent;")
        meta.addWidget(name_lbl)
        meta.addWidget(size_lbl)
        info_row.addLayout(meta)
        info_row.addStretch()
        inner.addLayout(info_row)

        # Inline image preview (shown after download)
        self._preview_lbl = QLabel()
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setStyleSheet("background: transparent;")
        self._preview_lbl.hide()
        inner.addWidget(self._preview_lbl)

        # Inline video surface, sized like the image preview. Created up front
        # but empty until the bytes arrive.
        if mime.startswith("video/"):
            self._video_widget = QVideoWidget()
            self._video_widget.setFixedSize(260, 150)
            self._video_widget.setStyleSheet("background: #000; border-radius: 8px;")
            self._video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            self._video_widget.hide()
            inner.addWidget(self._video_widget)

        # Inline audio/video playback (shown once data is available —
        # immediately for the sender, after download completes for the receiver)
        if mime.startswith("audio/") or mime.startswith("video/"):
            self._play_btn = QPushButton("▶")
            self._play_btn.setObjectName("fileDownloadBtn")
            self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._play_btn.setEnabled(False)
            self._play_btn.clicked.connect(self._toggle_playback)
            inner.addWidget(self._play_btn)

        # Action area
        if is_me:
            sent_lbl = QLabel(t("file_sent"))
            sent_lbl.setObjectName("tsLabel")
            inner.addWidget(sent_lbl)
        else:
            self._dl_btn = QPushButton(t("file_receiving"))
            self._dl_btn.setObjectName("fileDownloadBtn")
            self._dl_btn.setEnabled(False)
            self._dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._dl_btn.clicked.connect(self._download)
            inner.addWidget(self._dl_btn)

        ts = QLabel(datetime.now().strftime("%H:%M"))
        ts.setObjectName("tsLabel")
        ts.setAlignment(
            Qt.AlignmentFlag.AlignRight if is_me else Qt.AlignmentFlag.AlignLeft
        )
        inner.addWidget(ts)

        if is_me:
            row.addStretch()
            row.addWidget(self._bubble)
        else:
            row.addWidget(self._bubble)
            row.addStretch()

        outer.addLayout(row)

        self._init_blur()
        if blur_messages:
            self.enable_blur()

    def set_ready(self, data: bytes) -> None:
        self._data = data
        if hasattr(self, "_dl_btn"):
            self._dl_btn.setText(t("file_download"))
            self._dl_btn.setEnabled(True)

        if self._mime.startswith("audio/"):
            self._setup_audio(data)
            return

        if self._mime.startswith("video/"):
            self._setup_video(data)
            return

        if not self._mime.startswith("image/"):
            return

        try:
            is_gif = self._mime == "image/gif" or data[:6] in (b"GIF87a", b"GIF89a")
            if is_gif and self._start_gif(data):
                return

            px = QPixmap()
            px.loadFromData(data)
            if not px.isNull():
                px = px.scaledToWidth(
                    min(240, px.width()),
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._preview_lbl.setPixmap(px)
                self._preview_lbl.show()
        except Exception:
            pass

    def _start_gif(self, data: bytes) -> bool:
        gif_bytes = QByteArray(data)
        buf = QBuffer(self)
        buf.setData(gif_bytes)
        if not buf.open(QBuffer.OpenModeFlag.ReadOnly):
            return False
        movie = QMovie(self)
        movie.setDevice(buf)
        # CacheAll would decode and retain every frame at its native
        # resolution for the lifetime of the widget — a large real-world
        # animated GIF (many frames, high resolution) can balloon to hundreds
        # of MB of retained pixmaps even though the on-screen preview is
        # capped at 240px wide, risking an out-of-memory crash. CacheNone lets
        # Qt decode frames on the fly instead.
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        if not movie.jumpToFrame(0):
            buf.close()
            return False
        first = movie.currentPixmap()
        if first.isNull():
            buf.close()
            return False
        if first.width() > 0:
            width = min(240, first.width())
            scale = width / first.width()
            movie.setScaledSize(QSize(width, max(1, round(first.height() * scale))))
        # Lock preview size to prevent GIF frames from causing layout recalculations
        self._preview_lbl.setFixedSize(movie.scaledSize())
        self._gif_bytes = gif_bytes
        self._gif_buffer = buf
        self._gif_movie = movie
        self._preview_lbl.setMovie(movie)
        self._preview_lbl.show()
        movie.start()
        return True

    def _setup_audio(self, data: bytes) -> None:
        if not hasattr(self, "_play_btn"):
            return
        try:
            # QMediaPlayer needs a real file/URL source (no reliable
            # in-memory-buffer path across backends the way QMovie has for
            # GIFs), so write to a temp file named with the right extension
            # for the backend's content-type sniffing.
            ext = _AUDIO_EXTENSIONS.get(self._mime, "")
            fd, path = tempfile.mkstemp(suffix=ext, prefix="audio_", dir=_media_dir())
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            _AUDIO_TMP_PATHS.add(path)
            self._audio_tmp_path = path
            # The player — and the decoder behind it — only on ▶ (see
            # _ensure_player): a received file is not parsed unasked.
            self._play_btn.setEnabled(True)
        except Exception:
            pass

    def _setup_video(self, data: bytes) -> None:
        """Play a received video inline, in the bubble.

        Same temp-file dance as `_setup_audio` — QMediaPlayer has no reliable
        in-memory source across backends — and the file is registered for the
        panic-time purge so a video never outlives the session on disk.
        """
        if self._video_widget is None or not hasattr(self, "_play_btn"):
            return
        try:
            ext = _VIDEO_EXTENSIONS.get(self._mime, "")
            if not ext:
                # Unknown container: keep the extension the sender used, which
                # is the best hint the backend's sniffing will get.
                ext = Path(self._filename).suffix
            fd, path = tempfile.mkstemp(suffix=ext, prefix="video_", dir=_media_dir())
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            _AUDIO_TMP_PATHS.add(path)
            self._audio_tmp_path = path
            self._play_btn.setEnabled(True)
            # Kept hidden while the bubble is blurred: a QVideoWidget paints
            # through a native surface that QGraphicsBlurEffect never touches,
            # so a "blurred" bubble would otherwise play the video in the clear.
            if not getattr(self, "_blurred", False):
                self._video_widget.show()
        except Exception:
            pass

    def _apply_blur(self) -> None:
        super()._apply_blur()
        if getattr(self, "_blurred", False) and self._video_widget is not None:
            if self._audio_player is not None:
                try:
                    self._audio_player.pause()
                except Exception:
                    pass
            self._video_widget.hide()

    def _remove_blur(self) -> None:
        super()._remove_blur()
        if not getattr(self, "_blurred", False) and self._video_widget is not None:
            if self._audio_player is not None:
                self._video_widget.show()

    def _ensure_player(self) -> bool:
        """Create the player on the first ▶ (audit H12).

        Handing the file to QMediaPlayer starts FFmpeg probing it — the
        decoder is the part a crafted file attacks — so a received file is
        only decoded when its user asks to play it.
        """
        if self._audio_player is not None:
            return True
        path = getattr(self, "_audio_tmp_path", None)
        if not path:
            return False
        self._audio_output = QAudioOutput(self)
        self._audio_player = QMediaPlayer(self)
        self._audio_player.setAudioOutput(self._audio_output)
        if self._video_widget is not None:
            self._audio_player.setVideoOutput(self._video_widget)
            # Kept hidden while blurred: a QVideoWidget paints through a native
            # surface that QGraphicsBlurEffect never touches.
            if not getattr(self, "_blurred", False):
                self._video_widget.show()
        self._audio_player.setSource(QUrl.fromLocalFile(path))
        self._audio_player.playbackStateChanged.connect(self._on_playback_state_changed)
        return True

    def _toggle_playback(self) -> None:
        try:
            if not self._ensure_player():
                return
        except Exception:
            return
        try:
            if self._audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._audio_player.pause()
            else:
                self._audio_player.play()
        except Exception:
            pass

    def _on_playback_state_changed(self, state) -> None:
        try:
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self._play_btn.setText("⏸")
            else:
                self._play_btn.setText("▶")
        except Exception:
            pass

    def update_progress(self, received: int, total: int) -> None:
        if hasattr(self, "_dl_btn") and self._data is None:
            pct = int(received / max(total, 1) * 100)
            self._dl_btn.setText(f"{t('file_receiving')} {pct}%")

    def _download(self) -> None:
        if self._data is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, t("file_save_as"), self._filename)
        if path:
            Path(path).write_bytes(self._data)


# ──────────────────────────────────────────────────────────────────────
# QR code popup
# ──────────────────────────────────────────────────────────────────────

class _QRPopup(_Popup):
    def __init__(self, main_win: "MainWindow", onion_url: str) -> None:
        super().__init__(main_win)
        panel = self._make_panel(340, 420)
        panel.setObjectName("qrPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        title_row = QWidget()
        title_row.setFixedHeight(52)
        tr_lay = QHBoxLayout(title_row)
        tr_lay.setContentsMargins(24, 0, 16, 0)
        title_lbl = QLabel(t("qr_title"))
        title_lbl.setObjectName("popupTitle")
        tr_lay.addWidget(title_lbl)
        tr_lay.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("popupCloseBtn")
        close_btn.clicked.connect(self.close)
        tr_lay.addWidget(close_btn)
        lay.addWidget(title_row)
        lay.addWidget(self._hsep())

        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(28, 20, 28, 24)
        il.setSpacing(14)
        lay.addWidget(inner)

        qr_lbl = QLabel()
        qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            import qrcode as _qrcode
            qr = _qrcode.QRCode(box_size=1, border=3)
            # Encodes the bare address, same as the label and the copy button:
            # this QR is scanned to be pasted into another Haze client's "Join"
            # field. Encoding a bare ".onion" URL would instead tempt the
            # scanning phone's camera app into opening it in a browser that has
            # no Tor to resolve it with.
            qr.add_data(onion_url.removesuffix(".onion"))
            qr.make(fit=True)
            matrix = qr.get_matrix()
            n = len(matrix)
            cell = 6
            img = QImage(n * cell, n * cell, QImage.Format.Format_RGB32)
            img.fill(Qt.GlobalColor.white)
            qr_painter = QPainter(img)
            qr_painter.setPen(Qt.PenStyle.NoPen)
            qr_painter.setBrush(Qt.GlobalColor.black)
            for ry, row in enumerate(matrix):
                for rx, val in enumerate(row):
                    if val:
                        qr_painter.drawRect(rx * cell, ry * cell, cell, cell)
            qr_painter.end()
            px = QPixmap.fromImage(img)
            qr_lbl.setPixmap(px)
        except Exception as e:
            qr_lbl.setText(f"QR: {e}")
            qr_lbl.setStyleSheet("color: #ff3b30;")
        il.addWidget(qr_lbl)

        addr_lbl = QLabel(onion_url.removesuffix(".onion"))
        addr_lbl.setObjectName("tsLabel")
        addr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        addr_lbl.setWordWrap(True)
        addr_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        il.addWidget(addr_lbl)
        il.addStretch()

        # Copies the bare address, matching the label, the QR payload and the
        # mobile client. The Tor Browser button below is the one that hands over
        # a full "http://…onion" URL.
        copy_btn = QPushButton(t("qr_copy"))
        copy_btn.setObjectName("sendBtn")
        copy_btn.setFixedHeight(40)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(onion_url.removesuffix(".onion"))
        )
        il.addWidget(copy_btn)

        tb_btn = QPushButton(t("open_in_tor_browser"))
        tb_btn.setObjectName("copyBtn")
        tb_btn.setFixedHeight(36)
        tb_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tb_btn.setToolTip(t("open_in_tor_browser_hint"))
        tb_btn.clicked.connect(lambda: main_win._open_in_tor_browser())
        il.addWidget(tb_btn)


# ──────────────────────────────────────────────────────────────────────
# Settings overlay popup
# ──────────────────────────────────────────────────────────────────────

class _SettingsPopup(_Popup):
    def __init__(self, main_win: "MainWindow") -> None:
        super().__init__(main_win)
        self._main_win = main_win
        settings = main_win._settings

        panel = self._make_panel(460, 680)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Title row
        title_row = QWidget()
        title_row.setFixedHeight(52)
        tr_lay = QHBoxLayout(title_row)
        tr_lay.setContentsMargins(24, 0, 16, 0)
        title_lbl = QLabel(t("settings"))
        title_lbl.setObjectName("popupTitle")
        tr_lay.addWidget(title_lbl)
        tr_lay.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("popupCloseBtn")
        close_btn.clicked.connect(self.close)
        tr_lay.addWidget(close_btn)
        lay.addWidget(title_row)
        lay.addWidget(self._hsep())

        # Scrollable body — the Tor connection section made the panel taller
        # than a short window can show, and the Save button must stay reachable.
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(28, 20, 28, 8)
        il.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll.viewport().setStyleSheet("background: transparent;")
        lay.addWidget(scroll, 1)

        # Notifications
        notif_lbl = QLabel(t("notifications"))
        notif_lbl.setObjectName("popupSectionLabel")
        il.addWidget(notif_lbl)

        self._notif_cb = _CheckBox(t("enable_notifications"))
        self._notif_cb.setChecked(settings.get("notifications_enabled", True))
        il.addWidget(self._notif_cb)

        self._content_cb = _CheckBox(t("show_message_content"))
        self._content_cb.setChecked(settings.get("notifications_show_content", True))
        self._content_cb.setEnabled(self._notif_cb.isChecked())
        il.addWidget(self._content_cb)
        self._notif_cb.toggled.connect(self._content_cb.setEnabled)

        il.addWidget(self._hsep())

        # Theme
        theme_lbl = QLabel(t("theme"))
        theme_lbl.setObjectName("popupSectionLabel")
        il.addWidget(theme_lbl)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(10)
        current_theme = settings.get("theme", "haze")
        self._theme_btns: dict[str, QPushButton] = {}
        for tid, tdata in THEMES.items():
            btn = QPushButton(tdata["name"])
            btn.setCheckable(True)
            btn.setChecked(tid == current_theme)
            btn.setFixedHeight(36)
            c = tdata["swatch"]
            btn.setStyleSheet(
                f"QPushButton{{background:rgba(255,255,255,5);color:#787878;"
                f"border:1px solid #282828;border-radius:8px;"
                f"font-size:11px;font-weight:700;letter-spacing:0.5px;}}"
                f"QPushButton:checked{{background:rgba(255,255,255,11);color:#eeeeee;"
                f"border:1px solid {c}cc;}}"
                f"QPushButton:hover{{background:rgba(255,255,255,9);color:#bbbbbb;}}"
            )
            btn.clicked.connect(lambda _=False, t_id=tid: self._select_theme(t_id))
            swatch_row.addWidget(btn)
            self._theme_btns[tid] = btn
        il.addLayout(swatch_row)

        il.addWidget(self._hsep())

        # Disappearing messages
        disap_lbl = QLabel(t("disappearing_messages"))
        disap_lbl.setObjectName("popupSectionLabel")
        il.addWidget(disap_lbl)

        disap_row = QHBoxLayout()
        disap_row.setSpacing(6)
        current_disap = settings.get("disappearing_messages", 0)
        self._disap_btns: dict[int, QPushButton] = {}
        for secs, label in ((0, t("disappear_off")), (30, t("disappear_30s")),
                             (300, t("disappear_5m")), (3600, t("disappear_1h"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(secs == current_disap)
            b.setFixedHeight(32)
            b.setStyleSheet(
                "QPushButton{background:rgba(255,255,255,4);color:#606060;border:1px solid #1e1e20;"
                "border-radius:7px;font-size:10px;font-weight:600;}"
                "QPushButton:checked{background:rgba(255,255,255,10);color:#cccccc;border-color:#303030;}"
                "QPushButton:hover{background:rgba(255,255,255,7);}"
            )
            b.clicked.connect(lambda _=False, s=secs: self._select_disap(s))
            disap_row.addWidget(b)
            self._disap_btns[secs] = b
        il.addLayout(disap_row)

        il.addWidget(self._hsep())

        # Blur messages
        privacy_lbl = QLabel(t("privacy"))
        privacy_lbl.setObjectName("popupSectionLabel")
        il.addWidget(privacy_lbl)

        self._blur_cb = _CheckBox(t("blur_messages"))
        self._blur_cb.setChecked(settings.get("blur_messages", False))
        il.addWidget(self._blur_cb)

        il.addWidget(self._hsep())

        # Tor connection method — bridges / pluggable transports for networks
        # where Tor itself is blocked. Tor is already running by the time this
        # panel opens, so a change only lands on the next launch.
        tor_lbl = QLabel(t("tor_connection"))
        tor_lbl.setObjectName("popupSectionLabel")
        il.addWidget(tor_lbl)

        self._tor_conn = TorConnectionWidget(settings)
        il.addWidget(self._tor_conn)

        tor_note = QLabel(t("tor_conn_restart_note"))
        tor_note.setWordWrap(True)
        tor_note.setStyleSheet("color:#4c4c4c;font-size:9px;background:transparent;")
        il.addWidget(tor_note)

        il.addWidget(self._hsep())

        # Vault lock
        vault_sec_lbl = QLabel(t("vault_lock"))
        vault_sec_lbl.setObjectName("popupSectionLabel")
        il.addWidget(vault_sec_lbl)

        vault_btns_row = QHBoxLayout()
        lock_btn = QPushButton(t("vault_lock_set"))
        lock_btn.setObjectName("copyBtn")
        lock_btn.setFixedHeight(32)
        lock_btn.clicked.connect(self._set_vault_lock)
        vault_btns_row.addWidget(lock_btn)

        decoy_btn = QPushButton(t("vault_decoy_set"))
        decoy_btn.setObjectName("copyBtn")
        decoy_btn.setFixedHeight(32)
        decoy_btn.setToolTip(t("vault_decoy_hint"))
        decoy_btn.clicked.connect(self._set_vault_decoy)
        vault_btns_row.addWidget(decoy_btn)
        il.addLayout(vault_btns_row)

        il.addStretch()

        # Pinned outside the scroll area so it is always reachable.
        footer = QWidget()
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(28, 10, 28, 20)
        save_btn = QPushButton(t("save"))
        save_btn.setObjectName("sendBtn")
        save_btn.setFixedHeight(44)
        save_btn.clicked.connect(self._save_and_close)
        fl.addWidget(save_btn)
        lay.addWidget(footer)

    def _select_disap(self, secs: int) -> None:
        for s, b in self._disap_btns.items():
            b.setChecked(s == secs)

    def _set_vault_lock(self) -> None:
        pw, ok = QInputDialog.getText(self, t("vault_lock"), t("vault_password_new"),
                                      QLineEdit.EchoMode.Password)
        if ok:
            if pw:
                self._main_win._settings["vault_lock_hash"] = make_lock_hash(pw)
            else:
                self._main_win._settings["vault_lock_hash"] = ""
            _app_settings.save(self._main_win._settings)

    def _set_vault_decoy(self) -> None:
        pw, ok = QInputDialog.getText(self, t("vault_decoy"), t("vault_password_new"),
                                      QLineEdit.EchoMode.Password)
        if ok:
            if pw:
                self._main_win._settings["vault_decoy_hash"] = make_decoy_hash(pw)
            else:
                self._main_win._settings["vault_decoy_hash"] = ""
            _app_settings.save(self._main_win._settings)

    def _select_theme(self, theme_id: str) -> None:
        for tid, btn in self._theme_btns.items():
            btn.setChecked(tid == theme_id)

    def get_settings(self) -> dict:
        selected_theme = next(
            (tid for tid, btn in self._theme_btns.items() if btn.isChecked()), "haze"
        )
        selected_disap = next(
            (secs for secs, btn in self._disap_btns.items() if btn.isChecked()), 0
        )
        out = {
            "notifications_enabled": self._notif_cb.isChecked(),
            "notifications_show_content": self._content_cb.isChecked(),
            "theme": selected_theme,
            "disappearing_messages": selected_disap,
            "blur_messages": self._blur_cb.isChecked(),
        }
        self._tor_conn.apply_to(out)
        return out

    def _save_and_close(self) -> None:
        error = self._tor_conn.validate()
        if error:
            self._tor_conn.show_error(error)
            return
        s = self.get_settings()
        self._main_win._settings.update(s)
        _app_settings.save(self._main_win._settings)
        self._main_win._apply_theme(s.get("theme", "haze"))
        self._main_win._apply_blur_setting()
        self.close()


# ──────────────────────────────────────────────────────────────────────
# Vault overlay popup
# ──────────────────────────────────────────────────────────────────────

class _VaultPopup(_Popup):
    def __init__(self, main_win: "MainWindow", messages: list, participants: list) -> None:
        super().__init__(main_win)
        self._main_win = main_win
        self._messages = messages
        self._participants = participants
        self._pending_session: dict | None = None
        self._decoy_mode = False
        self._vault_password: str = ""

        panel = self._make_panel(520, 640)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_lock_page())   # 0 — always first (skip if no lock)
        self._stack.addWidget(self._build_list_page())   # 1
        self._stack.addWidget(self._build_save_page())   # 2
        self._stack.addWidget(self._build_pass_page())   # 3
        self._stack.addWidget(self._build_view_page())   # 4

        # If no vault lock is set, skip straight to list
        if not main_win._settings.get("vault_lock_hash", ""):
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)

    # ── Page 0: vault lock ────────────────────────────────────────────

    def _build_lock_page(self) -> QWidget:
        w, lay = self._page_frame()
        lay.addWidget(self._title_row(t("vault_locked")))
        lay.addWidget(self._hsep())

        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(28, 30, 28, 24)
        il.setSpacing(14)
        lay.addWidget(inner)

        lbl = QLabel(t("vault_locked"))
        lbl.setObjectName("popupSectionLabel")
        il.addWidget(lbl)

        self._lock_input = QLineEdit()
        self._lock_input.setFixedHeight(40)
        self._lock_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._lock_input.returnPressed.connect(self._do_unlock)
        il.addWidget(self._lock_input)

        self._lock_err = QLabel("")
        self._lock_err.setStyleSheet("color: #ff3b30; font-size: 11px;")
        il.addWidget(self._lock_err)

        il.addStretch()

        unlock_btn = QPushButton(t("vault_unlock"))
        unlock_btn.setObjectName("sendBtn")
        unlock_btn.setFixedHeight(44)
        unlock_btn.clicked.connect(self._do_unlock)
        il.addWidget(unlock_btn)

        return w

    def _do_unlock(self) -> None:
        pw = self._lock_input.text()
        settings = self._main_win._settings

        if check_decoy(pw, settings.get("vault_decoy_hash", "")):
            self._upgrade_legacy_hashes(pw, settings, key="vault_decoy_hash")
            self._decoy_mode = True
            for s in _app_vault.list_sessions():
                _app_vault.delete_session(s["path"])
            self._stack.setCurrentIndex(1)
            return

        if check_lock(pw, settings.get("vault_lock_hash", "")):
            self._decoy_mode = False
            self._vault_password = pw
            self._upgrade_legacy_hashes(pw, settings)
            self._stack.setCurrentIndex(1)
        else:
            self._lock_err.setText(t("vault_lock_wrong"))

    def _upgrade_legacy_hashes(self, password: str, settings: dict,
                               key: str = "vault_lock_hash") -> None:
        """Re-hash a fixed-salt lock (or decoy) hash, now that we have its password.

        Existing users keep their password; only the stored digest changes —
        to scrypt with a salt of its own — so a settings file copied off the
        device stops being cheap to crack. Each hash is upgraded when its own
        password is entered: the lock's on a normal unlock, the decoy's when
        the decoy is used (re-saving settings shows nothing on screen).
        """
        stored = settings.get(key, "")
        if not is_legacy_hash(stored):
            return
        make = make_decoy_hash if key == "vault_decoy_hash" else make_lock_hash
        settings[key] = make(password)
        _app_settings.save(settings)
        log.info("%s upgraded to salted scrypt", key)

    # ── Page helpers ──────────────────────────────────────────────────

    def _page_frame(self) -> tuple:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        return w, lay

    def _title_row(self, title: str, show_back: bool = False) -> QWidget:
        row = QWidget()
        row.setFixedHeight(52)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(24, 0, 16, 0)
        if show_back:
            back = QPushButton("←")
            back.setObjectName("popupCloseBtn")
            back.clicked.connect(lambda: self._stack.setCurrentIndex(1))
            rl.addWidget(back)
            rl.addSpacing(10)
        lbl = QLabel(title)
        lbl.setObjectName("popupTitle")
        rl.addWidget(lbl)
        rl.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setObjectName("popupCloseBtn")
        x_btn.clicked.connect(self.close)
        rl.addWidget(x_btn)
        return row

    # ── Page 1: session list ──────────────────────────────────────────

    def _build_list_page(self) -> QWidget:
        w, lay = self._page_frame()
        lay.addWidget(self._title_row(t("vault")))
        lay.addWidget(self._hsep())

        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(24, 16, 24, 20)
        il.setSpacing(12)
        lay.addWidget(inner)

        save_btn = QPushButton(t("vault_save_session"))
        save_btn.setObjectName("sendBtn")
        save_btn.setFixedHeight(42)
        save_btn.clicked.connect(lambda: self._stack.setCurrentIndex(2))
        il.addWidget(save_btn)

        il.addWidget(self._hsep())

        sessions_lbl = QLabel(t("vault_saved_sessions"))
        sessions_lbl.setObjectName("popupSectionLabel")
        il.addWidget(sessions_lbl)

        self._sessions_widget = QWidget()
        self._sessions_widget.setStyleSheet("background: transparent;")
        self._sessions_lay = QVBoxLayout(self._sessions_widget)
        self._sessions_lay.setContentsMargins(0, 0, 0, 0)
        self._sessions_lay.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidget(self._sessions_widget)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll.viewport().setStyleSheet("background: transparent;")
        il.addWidget(scroll)

        self._refresh_sessions()
        return w

    def _refresh_sessions(self) -> None:
        while self._sessions_lay.count():
            item = self._sessions_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self._decoy_mode:
            empty = QLabel(t("vault_decoy_active"))
            empty.setStyleSheet("color: #444; font-size: 12px; padding: 20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._sessions_lay.addWidget(empty)
            self._sessions_lay.addStretch()
            return
        sessions = _app_vault.list_sessions()
        if not sessions:
            empty = QLabel(t("vault_empty"))
            empty.setStyleSheet("color: #444; font-size: 12px; padding: 20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._sessions_lay.addWidget(empty)
        else:
            for s in sessions:
                self._sessions_lay.addWidget(self._make_session_row(s))
        self._sessions_lay.addStretch()

    def _make_session_row(self, session: dict) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            "QFrame { background: rgba(255,255,255,4); border-radius: 8px; border: none; }"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(8)

        name = session["filename"].replace(".hzv", "")
        parts = name.split("_", 2)
        display = parts[2].replace("_", " ") if len(parts) >= 3 else name
        if len(parts) >= 2:
            d, ti = parts[0], parts[1]
            subtitle = f"{d[:4]}-{d[4:6]}-{d[6:]}  {ti[:2]}:{ti[2:4]}"
        else:
            subtitle = ""

        info = QVBoxLayout()
        name_lbl = QLabel(display)
        name_lbl.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold;")
        info.addWidget(name_lbl)
        if subtitle:
            date_lbl = QLabel(subtitle)
            date_lbl.setStyleSheet("color: #555; font-size: 10px;")
            info.addWidget(date_lbl)
        rl.addLayout(info)
        rl.addStretch()

        view_btn = QPushButton(t("vault_view"))
        view_btn.setObjectName("copyBtn")
        view_btn.setFixedHeight(26)
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.clicked.connect(lambda _=False, s=session: self._start_view(s))
        rl.addWidget(view_btn)

        del_btn = QPushButton("✕")
        del_btn.setObjectName("popupCloseBtn")
        del_btn.setFixedSize(26, 26)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda _=False, s=session: self._delete_session(s))
        rl.addWidget(del_btn)

        return row

    def _start_view(self, session: dict) -> None:
        self._pending_session = session
        try:
            data = _app_vault.load_session(self._vault_password, session["path"])
            self._populate_view_page(data)
            self._stack.setCurrentIndex(4)
        except Exception:
            self._pass_input.clear()
            self._pass_err.setText(t("vault_wrong_password"))
            self._stack.setCurrentIndex(3)

    def _delete_session(self, session: dict) -> None:
        _app_vault.delete_session(session["path"])
        self._refresh_sessions()

    # ── Page 2: save form ─────────────────────────────────────────────

    def _build_save_page(self) -> QWidget:
        w, lay = self._page_frame()
        lay.addWidget(self._title_row(t("vault_save_session"), show_back=True))
        lay.addWidget(self._hsep())

        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(28, 20, 28, 24)
        il.setSpacing(12)
        lay.addWidget(inner)

        name_lbl = QLabel(t("vault_session_name"))
        name_lbl.setObjectName("popupSectionLabel")
        il.addWidget(name_lbl)

        self._save_name = QLineEdit()
        self._save_name.setFixedHeight(40)
        self._save_name.setPlaceholderText("My session…")
        il.addWidget(self._save_name)

        self._save_err = QLabel("")
        self._save_err.setStyleSheet("color: #ff3b30; font-size: 11px;")
        self._save_err.setWordWrap(True)
        il.addWidget(self._save_err)

        il.addStretch()

        do_save_btn = QPushButton(t("save"))
        do_save_btn.setObjectName("sendBtn")
        do_save_btn.setFixedHeight(44)
        do_save_btn.clicked.connect(self._do_save)
        il.addWidget(do_save_btn)

        return w

    def _do_save(self) -> None:
        name = self._save_name.text().strip()
        chat_msgs = [m for m in self._messages if m.get("type") == "chat"]

        if not name:
            self._save_err.setText(t("vault_session_name"))
            return
        if not chat_msgs:
            self._save_err.setText(t("vault_no_messages"))
            return

        try:
            _app_vault.save_session(self._vault_password, name, chat_msgs, self._participants)
            self._save_name.clear()
            self._save_err.clear()
            self._refresh_sessions()
            self._stack.setCurrentIndex(1)
        except Exception as exc:
            self._save_err.setText(str(exc))

    # ── Page 3: password prompt for viewing ───────────────────────────

    def _build_pass_page(self) -> QWidget:
        w, lay = self._page_frame()
        lay.addWidget(self._title_row(t("vault_password_prompt"), show_back=True))
        lay.addWidget(self._hsep())

        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(28, 30, 28, 24)
        il.setSpacing(14)
        lay.addWidget(inner)

        lbl = QLabel(t("vault_password_prompt"))
        lbl.setObjectName("popupSectionLabel")
        il.addWidget(lbl)

        self._pass_input = QLineEdit()
        self._pass_input.setFixedHeight(40)
        self._pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_input.returnPressed.connect(self._do_view)
        il.addWidget(self._pass_input)

        self._pass_err = QLabel("")
        self._pass_err.setStyleSheet("color: #ff3b30; font-size: 11px;")
        il.addWidget(self._pass_err)

        il.addStretch()

        view_btn = QPushButton(t("vault_view"))
        view_btn.setObjectName("sendBtn")
        view_btn.setFixedHeight(44)
        view_btn.clicked.connect(self._do_view)
        il.addWidget(view_btn)

        return w

    def _do_view(self) -> None:
        if not self._pending_session:
            return
        password = self._pass_input.text()
        try:
            data = _app_vault.load_session(password, self._pending_session["path"])
            self._populate_view_page(data)
            self._pass_err.clear()
            self._stack.setCurrentIndex(4)
        except Exception:
            self._pass_err.setText(t("vault_wrong_password"))

    # ── Page 4: session viewer ────────────────────────────────────────

    def _build_view_page(self) -> QWidget:
        w, lay = self._page_frame()

        title_row = QWidget()
        title_row.setFixedHeight(52)
        tr_lay = QHBoxLayout(title_row)
        tr_lay.setContentsMargins(24, 0, 16, 0)
        back_btn = QPushButton("←")
        back_btn.setObjectName("popupCloseBtn")
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        tr_lay.addWidget(back_btn)
        tr_lay.addSpacing(10)
        self._view_title_lbl = QLabel("")
        self._view_title_lbl.setObjectName("popupTitle")
        tr_lay.addWidget(self._view_title_lbl)
        tr_lay.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setObjectName("popupCloseBtn")
        x_btn.clicked.connect(self.close)
        tr_lay.addWidget(x_btn)
        lay.addWidget(title_row)
        lay.addWidget(self._hsep())

        self._view_inner = QWidget()
        self._view_inner_lay = QVBoxLayout(self._view_inner)
        self._view_inner_lay.setContentsMargins(24, 12, 24, 20)
        self._view_inner_lay.setSpacing(8)
        lay.addWidget(self._view_inner)

        return w

    def _populate_view_page(self, data: dict) -> None:
        while self._view_inner_lay.count():
            item = self._view_inner_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._view_title_lbl.setText(data.get("session_name", "Session"))

        ts_str = data.get("timestamp", "")[:16].replace("T", "  ")
        ts_lbl = QLabel(ts_str)
        ts_lbl.setStyleSheet("color: #555; font-size: 11px;")
        self._view_inner_lay.addWidget(ts_lbl)

        participants = ", ".join(data.get("participants", []))
        if participants:
            p_lbl = _plain(QLabel(participants))
            p_lbl.setStyleSheet("color: #606060; font-size: 11px;")
            self._view_inner_lay.addWidget(p_lbl)

        self._view_inner_lay.addWidget(self._hsep())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll.viewport().setStyleSheet("background: transparent;")

        msg_widget = QWidget()
        msg_widget.setStyleSheet("background: transparent;")
        msg_lay = QVBoxLayout(msg_widget)
        msg_lay.setContentsMargins(0, 8, 0, 8)
        msg_lay.setSpacing(6)

        for msg in data.get("messages", []):
            if msg.get("type") != "chat":
                continue
            nick = msg.get("nick", "?")
            content = msg.get("content", "")
            time_str = msg.get("time", "")

            bubble = QFrame()
            bubble.setObjectName("bubbleOther")
            b_lay = QVBoxLayout(bubble)
            b_lay.setContentsMargins(12, 8, 12, 6)
            b_lay.setSpacing(3)

            n_lbl = _plain(QLabel(nick.upper()))
            n_lbl.setObjectName("nickLabel")
            b_lay.addWidget(n_lbl)

            c_lbl = _plain(QLabel(content))
            c_lbl.setObjectName("msgText")
            c_lbl.setWordWrap(True)
            c_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            b_lay.addWidget(c_lbl)

            if time_str:
                t_lbl = QLabel(time_str)
                t_lbl.setObjectName("tsLabel")
                b_lay.addWidget(t_lbl)

            row_lay = QHBoxLayout()
            row_lay.addWidget(bubble)
            row_lay.addStretch()
            msg_lay.addLayout(row_lay)

        msg_lay.addStretch()
        scroll.setWidget(msg_widget)
        self._view_inner_lay.addWidget(scroll)


# ──────────────────────────────────────────────────────────────────────
# New-session overlay popup
# ──────────────────────────────────────────────────────────────────────

class _NewSessionPopup(_Popup):
    def __init__(self, main_win: "MainWindow", on_ready) -> None:
        super().__init__(main_win)
        self._main_win = main_win
        self._on_ready = on_ready
        self._mode = "join"
        self._worker: _SessionCreatorThread | None = None

        panel = self._make_panel(460, 490)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Title row
        title_row = QWidget()
        title_row.setFixedHeight(56)
        tr_lay = QHBoxLayout(title_row)
        tr_lay.setContentsMargins(28, 0, 18, 0)
        title_lbl = QLabel(t("new_session"))
        title_lbl.setObjectName("popupTitle")
        tr_lay.addWidget(title_lbl)
        tr_lay.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("popupCloseBtn")
        close_btn.clicked.connect(self.close)
        tr_lay.addWidget(close_btn)
        lay.addWidget(title_row)
        lay.addWidget(self._hsep())

        inner = QWidget()
        inner.setAutoFillBackground(False)
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(32, 24, 32, 28)
        il.setSpacing(6)
        lay.addWidget(inner)

        # Mode selector
        mode_lbl = QLabel(t("select_mode").upper() if "select_mode" in ("select_mode",) else "MODE")
        mode_lbl.setObjectName("popupSectionLabel")
        il.addWidget(mode_lbl)
        il.addSpacing(4)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self._host_btn = QPushButton(t("start_chat"))
        self._host_btn.setCheckable(True)
        self._host_btn.setObjectName("modeBtn")
        self._host_btn.setFixedHeight(42)
        self._join_btn = QPushButton(t("join"))
        self._join_btn.setCheckable(True)
        self._join_btn.setChecked(True)
        self._join_btn.setObjectName("modeBtn")
        self._join_btn.setFixedHeight(42)
        self._host_btn.clicked.connect(lambda: self._set_mode("host"))
        self._join_btn.clicked.connect(lambda: self._set_mode("join"))
        mode_row.addWidget(self._host_btn)
        mode_row.addWidget(self._join_btn)
        il.addLayout(mode_row)
        il.addSpacing(12)

        # Nick
        nick_lbl = QLabel(t("username").upper())
        nick_lbl.setObjectName("popupSectionLabel")
        il.addWidget(nick_lbl)
        il.addSpacing(4)
        self._nick_input = QLineEdit()
        self._nick_input.setText(main_win.nick)
        self._nick_input.setFixedHeight(42)
        il.addWidget(self._nick_input)
        il.addSpacing(12)

        # Onion (join only)
        self._onion_lbl = QLabel(t("onion_address").upper())
        self._onion_lbl.setObjectName("popupSectionLabel")
        il.addWidget(self._onion_lbl)
        il.addSpacing(4)
        self._onion_input = QLineEdit()
        self._onion_input.setFixedHeight(42)
        self._onion_input.setPlaceholderText(t("placeholder_onion"))
        self._onion_input.returnPressed.connect(self._start)
        il.addWidget(self._onion_input)
        il.addSpacing(12)

        # Session password
        self._pw_lbl = QLabel(t("session_password"))
        self._pw_lbl.setObjectName("popupSectionLabel")
        il.addWidget(self._pw_lbl)
        il.addSpacing(4)
        self._pw_input = QLineEdit()
        self._pw_input.setFixedHeight(42)
        self._pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_input.returnPressed.connect(self._start)
        il.addWidget(self._pw_input)
        il.addSpacing(8)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #606060; font-size: 11px;")
        self._status_lbl.setWordWrap(True)
        il.addWidget(self._status_lbl)

        self._err_lbl = QLabel("")
        self._err_lbl.setStyleSheet("color: #ff3b30; font-size: 11px;")
        self._err_lbl.setWordWrap(True)
        il.addWidget(self._err_lbl)

        il.addStretch()

        self._connect_btn = QPushButton(t("connect"))
        self._connect_btn.setObjectName("sendBtn")
        self._connect_btn.setFixedHeight(44)
        self._connect_btn.clicked.connect(self._start)
        il.addWidget(self._connect_btn)

        self._set_mode("join")

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self._host_btn.setChecked(mode == "host")
        self._join_btn.setChecked(mode == "join")
        self._onion_lbl.setVisible(mode == "join")
        self._onion_input.setVisible(mode == "join")
        self._pw_input.setPlaceholderText(
            t("session_password_host") if mode == "host" else t("session_password_join")
        )
        self._connect_btn.setText(t("start_chat") if mode == "host" else t("connect"))

    def _start(self) -> None:
        nick = self._nick_input.text().strip()
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        if not nick:
            self._err_lbl.setText(t("username_empty"))
            return
        if not all(c in allowed for c in nick) or len(nick) > 20:
            self._err_lbl.setText(t("username_chars"))
            return

        self._err_lbl.clear()
        pw = self._pw_input.text().strip()
        if self._mode == "join":
            onion = self._onion_input.text().strip().rstrip("/")
            if not onion:
                self._err_lbl.setText(t("onion_required"))
                return
            if not onion.endswith(".onion"):
                onion += ".onion"
            session = ChatSession(mode="join", nick=nick, onion_url=onion,
                                  session_password=pw)
            self._on_ready(session)
            self.close()
        else:
            self._pending_password = pw
            self._connect_btn.setEnabled(False)
            self._status_lbl.setText(t("creating_hs"))
            self._worker = _SessionCreatorThread(self._main_win.tor)
            self._worker.success.connect(self._on_hs_ready)
            self._worker.failure.connect(self._on_hs_error)
            self._worker.start()

    def _on_hs_ready(self, onion: str, service_id: str, local_port: int, http_port: int) -> None:
        session = ChatSession(
            mode="host",
            nick=self._nick_input.text().strip(),
            onion_url=onion,
            local_port=local_port,
            http_port=http_port,
            service_id=service_id,
            session_password=getattr(self, "_pending_password", ""),
        )
        self._on_ready(session)
        self.close()

    def _on_hs_error(self, error: str) -> None:
        self._connect_btn.setEnabled(True)
        self._status_lbl.clear()
        self._err_lbl.setText(error)


# ──────────────────────────────────────────────────────────────────────
# Main window
# ──────────────────────────────────────────────────────────────────────

class _RoundedWindowBg(QWidget):
    """Central widget with rounded corners and anti-aliased border."""

    _RADIUS = WINDOW_RADIUS

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._RADIUS, self._RADIUS)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        p.setClipping(False)
        pen_path = QPainterPath()
        pen_path.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            self._RADIUS, self._RADIUS,
        )
        p.setPen(QPen(QColor(40, 40, 44, 200), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(pen_path)


class MainWindow(QMainWindow):
    def __init__(
        self,
        mode: str,
        nick: str,
        tor: TorController,
        onion_url: str = "",
        session_password: str = "",
    ) -> None:
        super().__init__()
        self.nick = nick
        self.tor  = tor
        self._initial_session_password = session_password
        self._quitting = False
        self._settings: dict = _app_settings.load()

        # Multi-session state
        self._sessions: list[ChatSession] = []
        self._active: ChatSession | None = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        self.setWindowTitle("Haze")
        self.resize(1040, 700)
        self.setMinimumSize(800, 540)

        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self._build_ui()
        self._apply_theme(self._settings.get("theme", "haze"))
        self._setup_tray()
        self._fade_in()

        # Create and activate the initial session
        initial = ChatSession(
            mode=mode,
            nick=nick,
            onion_url=onion_url,
            local_port=tor.local_port if mode == "host" else 0,
            http_port=tor.http_port if mode == "host" else 0,
            session_password=session_password,
        )
        self._add_session(initial)

    # ── Close-to-tray helper ─────────────────────────────────────────

    def _close_to_tray(self) -> None:
        self.hide()
        self._tray.showMessage("Haze", t("tray_hidden"))

    # ── Window fade-in ───────────────────────────────────────────────

    def _fade_in(self) -> None:
        fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(fx)
        fx.setOpacity(0.0)
        a = QPropertyAnimation(fx, b"opacity", self)
        a.setDuration(500)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(lambda: self.setGraphicsEffect(None))
        a.start()
        self._win_anim = a
        self._win_fx   = fx

    # ── Badge pulse ──────────────────────────────────────────────────

    def _pulse_badge(self) -> None:
        b = self._title_bar._badge
        fx = QGraphicsOpacityEffect(b)
        b.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", b)
        a.setDuration(2800)
        a.setStartValue(1.0)
        a.setKeyValueAt(0.5, 0.3)
        a.setEndValue(1.0)
        a.setLoopCount(-1)
        a.setEasingCurve(QEasingCurve.Type.InOutSine)
        a.start()
        self._badge_anim = a
        self._badge_fx   = fx

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = _RoundedWindowBg(self)
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(8, 8, 8, 8)
        root_lay.setSpacing(0)

        self._title_bar = _TitleBar(self)
        root_lay.addWidget(self._title_bar)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        self._tab_bar = _SessionTabBar(self)
        self._tab_bar._add_btn.clicked.connect(self._open_new_session)
        self._tab_bar._leave_btn.clicked.connect(lambda: self._leave_session(self._active) if self._active else None)
        body_lay.addWidget(self._tab_bar)

        self._content_stack = QStackedWidget()
        body_lay.addWidget(self._content_stack)

        root_lay.addWidget(body)

        QTimer.singleShot(800, self._pulse_badge)

    # ── Session management ────────────────────────────────────────────

    def _add_session(self, session: ChatSession) -> None:
        content = self._create_session_content(session)
        self._content_stack.addWidget(content)
        self._sessions.append(session)

        self._tab_bar.add_tab(session, lambda s=session: self._switch_session(s))
        if session.tab_btn:
            session.tab_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            session.tab_btn.customContextMenuRequested.connect(
                lambda pos, s=session: self._session_tab_menu(pos, s)
            )

        self._start_session_network(session)
        self._switch_session(session)

    def _switch_session(self, session: ChatSession) -> None:
        if self._active is session:
            return
        self._active = session
        self._content_stack.setCurrentWidget(session.content_widget)
        self._tab_bar.set_active(session)
        self._title_bar.update_for_session(session)
        if session.connected:
            self._title_bar.set_badge(t("protocol_active"), active=True)
        else:
            self._title_bar.set_badge(t("protocol_lost"), active=False)

    def _close_session(self, session: ChatSession) -> None:
        if len(self._sessions) <= 1:
            return
        idx = self._sessions.index(session)
        next_session = self._sessions[idx - 1 if idx > 0 else 1]
        self._sessions.remove(session)

        session.bridge.stop()
        ping_timer = getattr(session, "_ping_timer", None)
        if ping_timer:
            ping_timer.stop()
        if session.service_id:
            try:
                self.tor.remove_service(session.service_id)
            except Exception:
                pass

        self._tab_bar.remove_tab(session)
        self._content_stack.removeWidget(session.content_widget)
        session.content_widget.deleteLater()

        if self._active is session:
            self._active = None
            self._switch_session(next_session)

    def _session_tab_menu(self, pos, session: ChatSession) -> None:
        if len(self._sessions) <= 1:
            return
        menu = QMenu(self)
        close_action = menu.addAction(t("close_session"))
        chosen = menu.exec(session.tab_btn.mapToGlobal(pos))
        if chosen == close_action:
            self._close_session(session)

    def _open_new_session(self) -> None:
        popup = _NewSessionPopup(self, self._add_session)
        popup.show()
        self._new_session_popup = popup

    # ── Per-session UI builders ───────────────────────────────────────

    def _create_session_content(self, session: ChatSession) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_session_sidebar(session))
        splitter.addWidget(self._build_session_chat(session))
        splitter.setSizes([200, 840])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        session.content_widget = splitter
        return splitter

    def _build_session_sidebar(self, session: ChatSession) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(200)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget()
        hdr.setObjectName("sidebarHeader")
        h = QHBoxLayout(hdr)
        h.setContentsMargins(16, 14, 16, 10)
        h.setSpacing(6)
        title = QLabel(t("online"))
        title.setObjectName("sidebarTitle")
        h.addWidget(title)
        h.addStretch()
        count_lbl = QLabel("1")
        count_lbl.setObjectName("participantCount")
        h.addWidget(count_lbl)
        lay.addWidget(hdr)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:rgba(255,255,255,4);")
        lay.addWidget(sep)

        user_list = QListWidget()
        user_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        user_list.setMouseTracking(True)
        user_list.viewport().setMouseTracking(True)
        user_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        user_list.setItemDelegate(_AvatarDelegate(user_list))
        if session.mode == "host":
            user_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            user_list.customContextMenuRequested.connect(
                lambda pos, s=session: self._user_context_menu(pos, s)
            )
        lay.addWidget(user_list)

        vault_btn = QPushButton(t("vault"))
        vault_btn.setObjectName("vaultBtn")
        vault_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        vault_btn.clicked.connect(lambda _=False, s=session: self._open_vault(s))
        lay.addWidget(vault_btn)

        session.user_list = user_list
        session.count_label = count_lbl

        self._add_user_to_list(session, session.nick, is_self=True)
        return panel

    def _build_session_chat(self, session: ChatSession) -> QWidget:
        outer = QWidget()
        outer.setAutoFillBackground(False)
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        # Search bar (hidden by default)
        search_bar = _SearchBar(session, outer)
        outer_lay.addWidget(search_bar)
        search_bar.hide()
        session.search_bar = search_bar

        chat_panel = _ChatPanel()

        scroll = _ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet("background: transparent;")
        scroll.viewport().setStyleSheet("background: transparent;")

        msg_container = QWidget()
        msg_container.setObjectName("msgArea")
        msg_container.setAutoFillBackground(False)
        msg_layout = QVBoxLayout(msg_container)
        msg_layout.setContentsMargins(0, 28, 0, 28)
        msg_layout.setSpacing(2)
        msg_layout.insertStretch(0)

        scroll.setWidget(msg_container)

        # Typing bar
        typing_bar = _TypingBar()
        chat_panel.add_scroll(scroll)
        chat_panel._lay.addWidget(typing_bar)
        chat_panel.add_input(self._build_session_input_bar(session))

        outer_lay.addWidget(chat_panel)

        scroll.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max, s=session, sc=scroll: (
                sc.verticalScrollBar().setValue(_max) if s.auto_scroll else None
            )
        )

        session.msg_layout = msg_layout
        session.scroll = scroll
        session.typing_bar = typing_bar
        return outer

    def _build_session_input_bar(self, session: ChatSession) -> QWidget:
        wrapper = QWidget()
        wrapper.setAutoFillBackground(False)
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)

        # Reply bar (hidden by default)
        reply_bar = QWidget()
        reply_bar.setObjectName("replyBar")
        rb_lay = QHBoxLayout(reply_bar)
        rb_lay.setContentsMargins(18, 6, 18, 6)
        rb_lay.setSpacing(6)
        reply_prefix = QLabel(t("reply_to") + ":")
        reply_prefix.setObjectName("replyBarLabel")
        rb_lay.addWidget(reply_prefix)
        reply_nick_lbl = _plain(QLabel(""))   # "<nick>  —  <their message>"
        reply_nick_lbl.setObjectName("replyBarNick")
        rb_lay.addWidget(reply_nick_lbl)
        rb_lay.addStretch()
        reply_close = QPushButton("✕")
        reply_close.setObjectName("replyBarClose")
        reply_close.setCursor(Qt.CursorShape.PointingHandCursor)
        reply_close.clicked.connect(lambda: self._cancel_reply(session))
        rb_lay.addWidget(reply_close)
        reply_bar.hide()
        session.reply_bar = reply_bar
        session._reply_nick_lbl = reply_nick_lbl
        wl.addWidget(reply_bar)

        bar = _InputBar()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(10)

        attach = QPushButton("+")
        attach.setObjectName("attachBtn")
        attach.setFixedSize(44, 44)
        attach.setCursor(Qt.CursorShape.PointingHandCursor)
        attach.setToolTip(t("attach_file"))
        attach.clicked.connect(lambda _=False, s=session: self._attach_file(s))
        lay.addWidget(attach)

        voice = _VoiceButton(lambda data, s=session: self._send_voice_note(s, data))
        lay.addWidget(voice)

        msg_input = QLineEdit()
        msg_input.setObjectName("messageInput")
        msg_input.setPlaceholderText(t("type_message"))
        msg_input.setFixedHeight(44)
        msg_input.returnPressed.connect(lambda s=session: self._send_message(s))
        msg_input.textChanged.connect(lambda text, s=session: self._on_input_changed(s, text))
        lay.addWidget(msg_input)

        send = QPushButton("↑")
        send.setObjectName("sendBtn")
        send.setFixedSize(44, 44)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.clicked.connect(lambda _=False, s=session: self._send_message(s))
        lay.addWidget(send)

        # Ctrl+F → toggle search bar
        sc = QShortcut(QKeySequence("Ctrl+F"), bar)
        sc.activated.connect(lambda s=session: self._toggle_search(s))

        session.msg_input = msg_input
        wl.addWidget(bar)
        return wrapper

    # ── Tray ─────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        self._tray = build_tray(self)
        self._tray.show()

    # ── Session network start ─────────────────────────────────────────

    def _start_session_network(self, session: ChatSession) -> None:
        session.bridge.start()
        session.bridge.event_received.connect(
            lambda event, s=session: self._safe_handle_event(s, event)
        )
        slogan = SloganWidget()
        session.slogan_widget = slogan
        slogan.setParent(session.scroll)
        slogan.hide()
        def _place_slogan():
            if session.slogan_widget is not slogan:
                return
            slogan.setGeometry(session.scroll.viewport().geometry())
            slogan.raise_()
            slogan.show()
        QTimer.singleShot(100, _place_slogan)
        if session.mode == "host":
            session.connected = True
            session._handshake_done = True
            self._append_system(session, t("chat_started"))
            session.bridge.start_server(
                session.nick, session.local_port, session.http_port,
                renew_circuit_cb=self.tor.renew_circuit,
                session_password=session.session_password,
                onion_address=session.onion_url,
            )
        else:
            self._append_system(session, t("connecting_to").format(session.onion_url))
            session.bridge.start_client(
                session.nick, session.onion_url, self.tor.socks_port,
                session_password=session.session_password,
            )
        QTimer.singleShot(500, lambda s=session: setattr(s, "auto_scroll", True))

    # ── Session event handler ─────────────────────────────────────────

    def _safe_handle_event(self, session: ChatSession, event: dict) -> None:
        try:
            self._handle_session_event(session, event)
        except Exception:
            pass

    def _handle_session_event(self, session: ChatSession, event: dict) -> None:
        kind = event.get("type")
        if kind == "connected":
            session.connected = True
            session._handshake_done = True
            self._append_system(session, t("connected"))
            self._remove_reconnect_banner(session)
            if session.mode == "join":
                self._start_ping_timer(session)
            if session is self._active:
                self._title_bar.set_badge(t("protocol_active"), active=True)
        elif kind == "chat":
            msg_id = event.get("msg_id", "")
            # A msg_id names one message for the whole session. A second message
            # claiming a known id — someone else's, or one that has already
            # disappeared — would become the target of that message's edits
            # and deletes, so it is dropped.
            if msg_id and msg_id in session.msg_owners:
                return
            event["time"] = datetime.now().strftime("%H:%M")
            session.messages.append(event)
            is_me = event["nick"] == session.nick
            # Use the sender's disappear setting from the payload only.
            # For own messages, fallback to local settings (join mode local echo).
            disappear = int(event.get("disappear_secs", 0)
                            or (self._settings.get("disappearing_messages", 0) if is_me else 0))

            # Group consecutive messages — only first in a run shows author label.
            prev = session.messages[-2] if len(session.messages) >= 2 else None
            show_author = (
                prev is None
                or prev.get("type") in ("join", "leave")
                or prev.get("deleted", False)
                or prev["nick"] != event["nick"]
            )

            def _on_disappear(s=session, mid=msg_id, ev=event, mine=is_me):
                # Every client runs the same timer and removes the message
                # locally; only its author also tells the others (a delete for
                # someone else's message is refused everywhere anyway).
                if mine:
                    s.bridge.send_delete(mid)
                w = s.msg_widgets.get(mid)
                if w:
                    s.msg_layout.removeWidget(w)
                    w.deleteLater()
                    s.msg_widgets.pop(mid, None)
                if ev in s.messages:
                    s.messages.remove(ev)

            bubble = MessageBubble(
                event["nick"], event["content"], is_me=is_me,
                msg_id=msg_id,
                on_delete=lambda mid, s=session: self._request_delete(s, mid),
                on_edit=lambda mid, content, s=session: self._request_edit(s, mid, content),
                on_reply=lambda nick, content, s=session: self._set_reply(s, nick, content),
                disappear_secs=disappear,
                on_disappear=_on_disappear if disappear > 0 else None,
                show_author=show_author,
                blur_messages=self._settings.get("blur_messages", False),
                reply_to_nick=event.get("reply_to_nick", ""),
                reply_to_content=event.get("reply_to_content", ""),
            )
            if msg_id:
                session.msg_widgets[msg_id] = bubble
                session.msg_owners[msg_id] = event["nick"]
            # Clear typing indicator when message arrives
            if session.typing_bar and not is_me:
                session.typing_bar.clear_nick(event["nick"])
            self._append_widget(session, bubble, animate=True)
            self._notify_message(event["nick"], event["content"])
            self._fade_slogan(session)
        elif kind == "join":
            self._add_user_to_list(session, event["nick"])
            self._append_system(session, t("joined").format(event["nick"]))
        elif kind == "leave":
            self._remove_user_from_list(session, event["nick"])
            self._append_system(session, t("left").format(event["nick"]))
        elif kind == "userlist":
            users = event.get("users", [])
            if session.mode == "join" and session.host_nick is None and users:
                session.host_nick = users[0]
            for u in users:
                if u != session.nick:
                    self._add_user_to_list(session, u)
        elif kind == "panic":
            nick = event["nick"]
            if nick == session.nick:
                # I pressed panic — full wipe dialog.
                self._append_system(session, t("panic_triggered"))
                self._show_panic_dialog(nick)
            elif session.mode == "host" or nick != session.host_nick:
                # A guest panicked — that guest is gone, the session goes on.
                # (Older hosts still relay a guest's panic to everyone.)
                self._append_system(session, f"⚠ {nick} pressed panic and left")
            else:
                # The host panicked — the session is over; I should leave.
                self._append_system(session, t("panic_triggered_by").format(nick))
                self._append_widget(session, PanicBanner(nick), animate=True)
                self._show_panic_dialog(nick)
        elif kind == "disconnected":
            if not session.connected or not getattr(session, "_handshake_done", False):
                self._append_system(session, t("auth_failed_msg"))
                if session.msg_input:
                    session.msg_input.setEnabled(False)
                if session is self._active:
                    self._title_bar.set_badge(t("protocol_lost"), active=False)
            else:
                session.connected = False
                self._append_system(session, t("disconnected"))
                if session is self._active:
                    self._title_bar.set_badge(t("protocol_lost"), active=False)
                if session.mode == "join":
                    self._append_reconnect_banner(session)
            self._stop_ping_timer(session)
        elif kind == "auth_failed":
            session.connected = False
            self._append_system(session, t("auth_failed_msg"))
            if session.msg_input:
                session.msg_input.setEnabled(False)
            if session is self._active:
                self._title_bar.set_badge(t("protocol_lost"), active=False)
            QMessageBox.warning(
                self, t("auth_failed_title"), t("auth_failed_msg")
            )
        elif kind == "typing":
            nick = event.get("nick", "")
            if nick != session.nick and session.typing_bar:
                if event.get("state"):
                    session.typing_bar.set_typing(nick)
                else:
                    session.typing_bar.clear_nick(nick)

        elif kind == "delete":
            msg_id = event.get("msg_id", "")
            # Only the author may delete a message. Anyone can see a msg_id, so
            # without this any participant could wipe anyone's message.
            if not msg_id or session.msg_owners.get(msg_id) != event.get("nick"):
                return
            # Only apply from event if it came from someone else
            # (own deletions are applied immediately in _request_delete)
            if event.get("nick") != session.nick:
                w = session.msg_widgets.get(msg_id)
                if w and isinstance(w, MessageBubble):
                    w.mark_deleted()
            for m in session.messages:
                if m.get("msg_id") == msg_id:
                    m["content"] = ""
                    m["deleted"] = True
                    break

        elif kind == "edit":
            msg_id = event.get("msg_id", "")
            # Only the author may edit a message — otherwise anyone could put
            # words in someone else's mouth, shown under that person's name.
            if not msg_id or session.msg_owners.get(msg_id) != event.get("nick"):
                return
            new_content = event.get("content", "")
            if event.get("nick") != session.nick:
                w = session.msg_widgets.get(msg_id)
                if w and isinstance(w, MessageBubble):
                    w.update_content(new_content)
            for m in session.messages:
                if m.get("msg_id") == msg_id:
                    m["content"] = new_content
                    m["edited"] = True
                    break

        elif kind == "pong":
            if session.ping_sent_at > 0:
                ms = int((time.time() - session.ping_sent_at) * 1000)
                session.ping_sent_at = 0
                self._title_bar._latency_dot.set_latency(ms)
                self._title_bar._latency_lbl.setText(f"{ms} ms")

        elif kind == "kicked":
            self._append_system(session, t("you_were_kicked"))
            if session.msg_input:
                session.msg_input.setEnabled(False)
        elif kind == "file_start":
            fid = event["file_id"]
            if event.get("nick") == session.nick:
                return
            total_size = int(event.get("total_size", 0))
            total_chunks = int(event.get("total_chunks", 0))
            # Enforce the same cap on receive as _attach_file enforces on
            # send (mirrors mobile's MAX_FILE_BYTES/MAX_FILE_CHUNKS check in
            # ChatViewModel.kt) — previously only the sender's own dialog
            # capped size, so a peer sending an oversized/malformed
            # total_chunks header would be reassembled with no limit at all.
            if total_size > MAX_FILE_BYTES or total_chunks > MAX_FILE_CHUNKS:
                return
            if total_chunks <= 0:
                return
            if len(session.file_buffers) >= MAX_INFLIGHT_TRANSFERS:
                return
            # The first sender keeps a file_id: a second file_start with the
            # same id would otherwise replace someone's transfer in flight.
            if fid in session.file_buffers:
                return
            # Group: only show author if previous message is from a different sender
            prev = session.messages[-1] if session.messages else None
            show_author = (
                prev is None
                or prev.get("type") in ("join", "leave")
                or prev.get("deleted", False)
                or prev.get("nick") != event.get("nick", "")
            )
            # Track in messages so grouping works across chat + files
            session.messages.append(event)
            widget = FileMessage(
                event.get("nick", "?"), str(event.get("filename", "file")),
                total_size, str(event.get("mime", "")), is_me=False,
                blur_messages=self._settings.get("blur_messages", False),
                show_author=show_author,
            )
            session.file_buffers[fid] = {
                # Chunks and the end are accepted from this sender only.
                "nick": event.get("nick"),
                "chunks": {},
                "total_chunks": total_chunks,
                "bytes": 0,
                "widget": widget,
            }
            self._append_widget(session, widget, animate=False)
        elif kind == "file_chunk":
            fid = event["file_id"]
            buf = session.file_buffers.get(fid)
            # file_ids are visible to everyone: a chunk from anyone but the
            # transfer's own sender would let them splice content into
            # someone else's file (first chunk at an index wins).
            if buf is None or buf["nick"] != event.get("nick"):
                return
            # Bound what a chunk may claim before storing it. Without this a peer
            # could declare a one-chunk file (passing the file_start caps) and
            # then stream unlimited chunks at arbitrary indices: every one was
            # kept, so the buffer grew until the client ran out of memory. The
            # mobile client already refuses out-of-range indices and writes each
            # slot once; this mirrors it.
            try:
                idx = int(event.get("chunk_index"))
            except (TypeError, ValueError):
                return
            if idx < 0 or idx >= buf["total_chunks"]:
                return
            if idx in buf["chunks"]:
                return                      # duplicate index — first one wins
            data = event.get("data", "")
            if not isinstance(data, str):
                return
            # base64 inflates by 4/3; compare against the raw-byte budget.
            buf["bytes"] += (len(data) * 3) // 4
            if buf["bytes"] > MAX_FILE_BYTES:
                session.file_buffers.pop(fid, None)
                return
            buf["chunks"][idx] = data
            buf["widget"].update_progress(len(buf["chunks"]), buf["total_chunks"])
        elif kind == "file_end":
            fid = event["file_id"]
            buf = session.file_buffers.get(fid)
            # Only the sender may finish (or, finishing early, truncate) it.
            if buf is None or buf["nick"] != event.get("nick"):
                return
            session.file_buffers.pop(fid, None)
            if buf:
                total = buf["total_chunks"]
                # A missing chunk used to be filled with nothing, silently
                # turning the file into a shorter, different one.
                if len(buf["chunks"]) != total:
                    log.warning("file transfer ended with %d of %d chunks; dropped",
                                len(buf["chunks"]), total)
                    return
                try:
                    data = b"".join(
                        base64.b64decode(buf["chunks"].get(i, "")) for i in range(total)
                    )
                    buf["widget"].set_ready(data)
                except Exception:
                    pass

    # ── Notifications ────────────────────────────────────────────────

    def _notify_message(self, nick: str, content: str) -> None:
        if self.isVisible() and not self.isMinimized():
            return
        if not self._settings.get("notifications_enabled", True):
            return
        msg = f"{nick}: {content}" if self._settings.get("notifications_show_content", True) else t("new_message_notification")
        self._tray.showMessage("Haze", _notification_safe(msg))

    # ── Settings ─────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        popup = _SettingsPopup(self)
        popup.show()
        self._settings_popup = popup

    def _apply_theme(self, theme_id: str) -> None:
        theme_qss = THEMES.get(theme_id, THEMES["haze"])["qss"]
        QApplication.instance().setStyleSheet(DARK_QSS + theme_qss)
        _AmbientLight._theme_id = theme_id

    def _apply_blur_setting(self) -> None:
        on = self._settings.get("blur_messages", False)
        for session in self._sessions:
            for w in session.msg_widgets.values():
                if isinstance(w, MessageBubble):
                    if on:
                        w.enable_blur(immediate=True)
                    else:
                        w.disable_blur()
            if session.msg_layout is not None:
                for i in range(session.msg_layout.count()):
                    w = session.msg_layout.itemAt(i).widget()
                    if isinstance(w, FileMessage):
                        if on:
                            w.enable_blur(immediate=True)
                        else:
                            w.disable_blur()

    # ── Vault ─────────────────────────────────────────────────────────

    def _open_vault(self, session: ChatSession | None = None) -> None:
        s = session or self._active
        if not s:
            return
        participants = [
            s.user_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(s.user_list.count())
        ]
        popup = _VaultPopup(self, s.messages, participants)
        popup.show()
        self._vault_popup = popup

    # ── File transfer ─────────────────────────────────────────────────

    def _attach_file(self, session: ChatSession | None = None) -> None:
        s = session or self._active
        if not s:
            return
        path, _ = QFileDialog.getOpenFileName(self, t("attach_file"))
        if not path:
            return
        # This runs directly off a button-click slot, so an unhandled
        # exception here (bad file, unreadable image/GIF, disk error) would
        # surface to the user as the whole app vanishing rather than a
        # message box — always show a real error instead.
        try:
            file_path = Path(path)
            data = file_path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                QMessageBox.warning(self, "Haze", t("file_too_large"))
                return
            filename = file_path.name
            mime, _ = mimetypes.guess_type(filename)
            mime = mime or "application/octet-stream"
            file_id = str(uuid.uuid4())
            widget = FileMessage(s.nick, filename, len(data), mime, is_me=True,
                                 blur_messages=self._settings.get("blur_messages", False))
            self._append_widget(s, widget, animate=False)
            if (mime.startswith("image/") or mime.startswith("audio/")
                    or mime.startswith("video/")):
                widget.set_ready(data)
            s.bridge.send_file(file_id, filename, mime, data)
            self._fade_slogan(s)
        except Exception:
            log.exception("attach_file failed")
            QMessageBox.warning(self, "Haze", t("file_send_error"))

    # ── Kick (host only) ──────────────────────────────────────────────

    def _user_context_menu(self, pos, session: ChatSession) -> None:
        item = session.user_list.itemAt(pos)
        if not item:
            return
        nick = item.data(Qt.ItemDataRole.UserRole)
        if nick == session.nick:
            return
        menu = QMenu(self)
        kick_action = menu.addAction(t("kick_user"))
        chosen = menu.exec(session.user_list.viewport().mapToGlobal(pos))
        if chosen == kick_action:
            session.bridge.kick_client(nick)

    # ── Typing indicator ─────────────────────────────────────────────

    def _on_input_changed(self, session: ChatSession, text: str) -> None:
        session.bridge.send_typing(bool(text))

    # ── Delete / Edit ────────────────────────────────────────────────

    def _request_delete(self, session: ChatSession, msg_id: str) -> None:
        session.bridge.send_delete(msg_id)
        # Apply immediately to local bubble (server won't echo back to the sender)
        w = session.msg_widgets.get(msg_id)
        if w and isinstance(w, MessageBubble):
            w.mark_deleted()

    def _request_edit(self, session: ChatSession, msg_id: str, old_content: str) -> None:
        text, ok = QInputDialog.getText(
            self, t("edit_dialog_title"), t("edit_dialog_label"),
            QLineEdit.EchoMode.Normal, old_content,
        )
        if ok and text.strip():
            session.bridge.send_edit(msg_id, text.strip())
            # Apply immediately to local bubble
            w = session.msg_widgets.get(msg_id)
            if w and isinstance(w, MessageBubble):
                w.update_content(text.strip())

    # ── Voice note ───────────────────────────────────────────────────

    def _send_voice_note(self, session: ChatSession, wav_data: bytes) -> None:
        try:
            file_id = str(uuid.uuid4())
            filename = f"voice_{datetime.now().strftime('%H%M%S')}.wav"
            widget = FileMessage(session.nick, filename, len(wav_data), "audio/wav", is_me=True,
                                 blur_messages=self._settings.get("blur_messages", False))
            self._append_widget(session, widget, animate=False)
            widget.set_ready(wav_data)
            session.bridge.send_file(file_id, filename, "audio/wav", wav_data)
            self._fade_slogan(session)
        except Exception:
            log.exception("send_voice_note failed")
            QMessageBox.warning(self, "Haze", t("file_send_error"))

    def _set_reply(self, session: ChatSession, nick: str, content: str) -> None:
        session._reply_to = {"nick": nick, "content": content}
        if session.reply_bar:
            lbl = getattr(session, "_reply_nick_lbl", None)
            if lbl:
                preview = content[:60] + ("…" if len(content) > 60 else "")
                lbl.setText(f"{nick}  —  {preview}")
            session.reply_bar.show()
        if session.msg_input:
            session.msg_input.setFocus()

    def _cancel_reply(self, session: ChatSession) -> None:
        session._reply_to = None
        if session.reply_bar:
            session.reply_bar.hide()

    # ── Search ───────────────────────────────────────────────────────

    def _toggle_search(self, session: ChatSession | None = None) -> None:
        s = session or self._active
        if not s or not s.search_bar:
            return
        if s.search_bar.isVisible():
            s.search_bar._close_self()
        else:
            s.search_bar.show()
            s.search_bar._input.setFocus()

    # ── QR popup ─────────────────────────────────────────────────────

    def _show_qr(self) -> None:
        if self._active and self._active.mode == "host" and self._active.onion_url:
            popup = _QRPopup(self, self._active.onion_url)
            popup.show()
            self._qr_popup = popup

    # ── Latency ping ─────────────────────────────────────────────────

    def _start_ping_timer(self, session: ChatSession) -> None:
        timer = QTimer(self)
        timer.timeout.connect(lambda s=session: self._send_ping(s))
        timer.start(30_000)
        session._ping_timer = timer  # keep alive

    def _send_ping(self, session: ChatSession) -> None:
        if session.mode == "join" and session.connected:
            session.ping_sent_at = time.time()
            session.bridge.send_ping(session.ping_sent_at)

    # ── Messaging ────────────────────────────────────────────────────

    def _send_message(self, session: ChatSession | None = None) -> None:
        s = session or self._active
        if not s or not s.msg_input:
            return
        text = s.msg_input.text().strip()
        if not text:
            return
        s.msg_input.clear()
        s.bridge.send_typing(False)

        reply_to = s._reply_to
        reply_nick = reply_to["nick"] if reply_to else None
        reply_content = reply_to["content"] if reply_to else None
        self._cancel_reply(s)

        if s.mode == "join":
            # Generate msg_id here so we can track this bubble for delete/edit
            msg_id = str(uuid.uuid4())
            disappear = self._settings.get("disappearing_messages", 0)
            s.bridge.send_chat(text, msg_id=msg_id,
                               reply_to_nick=reply_nick, reply_to_content=reply_content,
                               disappear_secs=disappear)

            def _on_disappear(s=s, mid=msg_id):
                s.bridge.send_delete(mid)
                w = s.msg_widgets.get(mid)
                if w:
                    s.msg_layout.removeWidget(w)
                    w.deleteLater()
                    s.msg_widgets.pop(mid, None)

            # Group own messages — only first in a run shows "YOU".
            prev = s.messages[-1] if s.messages else None
            show_author = (
                prev is None
                or prev.get("type") in ("join", "leave")
                or prev.get("deleted", False)
                or prev["nick"] != s.nick
            )

            bubble = MessageBubble(
                s.nick, text, is_me=True, msg_id=msg_id,
                on_delete=lambda mid, sess=s: self._request_delete(sess, mid),
                on_edit=lambda mid, content, sess=s: self._request_edit(sess, mid, content),
                on_reply=lambda nick, content, sess=s: self._set_reply(sess, nick, content),
                disappear_secs=disappear,
                on_disappear=_on_disappear if disappear > 0 else None,
                show_author=show_author,
                blur_messages=self._settings.get("blur_messages", False),
                reply_to_nick=reply_nick or "",
                reply_to_content=reply_content or "",
            )
            s.messages.append(
                {"type": "chat", "nick": s.nick, "content": text, "msg_id": msg_id}
            )
            s.msg_widgets[msg_id] = bubble
            s.msg_owners[msg_id] = s.nick
            self._append_widget(s, bubble, animate=True)
        else:
            msg_id = str(uuid.uuid4())
            disappear = self._settings.get("disappearing_messages", 0)
            s.bridge.send_chat(text, msg_id=msg_id,
                               reply_to_nick=reply_nick, reply_to_content=reply_content,
                               disappear_secs=disappear)
        self._fade_slogan(s)

    def _append_widget(self, session: ChatSession, widget: QWidget, animate: bool = False) -> None:
        session.msg_layout.addWidget(widget)
        if animate:
            _slide_in(widget)

    def _append_system(self, session: ChatSession, text: str) -> None:
        self._append_widget(session, SystemMessage(text), animate=True)

    def _fade_slogan(self, session: ChatSession) -> None:
        w = session.slogan_widget
        if w is None or not w.isVisible():
            return
        session.slogan_widget = None
        fx = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", w)
        a.setDuration(700)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(w.hide)
        a.start()

    def _append_reconnect_banner(self, session: ChatSession) -> None:
        if getattr(session, "_reconnect_banner", None) is not None:
            return
        banner = _ReconnectBanner(lambda _checked=False, s=session: self._reconnect_session(s))
        session._reconnect_banner = banner
        self._append_widget(session, banner, animate=True)

    def _remove_reconnect_banner(self, session: ChatSession) -> None:
        banner = getattr(session, "_reconnect_banner", None)
        if banner is None:
            return
        session._reconnect_banner = None
        if session.msg_layout:
            session.msg_layout.removeWidget(banner)
            banner.deleteLater()

    def _reconnect_session(self, session: ChatSession) -> None:
        if session.mode != "join" or not session.onion_url:
            return
        self._stop_ping_timer(session)
        try:
            session.bridge.event_received.disconnect()
        except Exception:
            pass
        session.bridge.stop()
        session._handshake_done = False
        session.bridge = _NetBridge()
        session.bridge.start()
        import time as _time
        _time.sleep(0.05)
        session.bridge.event_received.connect(
            lambda event, s=session: self._safe_handle_event(s, event)
        )
        self._append_system(session, t("connecting_to").format(session.onion_url.removesuffix(".onion")))
        session.bridge.start_client(
            session.nick, session.onion_url, self.tor.socks_port,
            session_password=session.session_password,
        )

    def _start_ping_timer(self, session: ChatSession) -> None:
        timer = QTimer(self)
        timer.timeout.connect(lambda s=session: self._send_ping(s))
        timer.start(30_000)
        session._ping_timer = timer

    def _stop_ping_timer(self, session: ChatSession) -> None:
        timer = getattr(session, "_ping_timer", None)
        if timer is not None:
            timer.stop()
            session._ping_timer = None

    # ── User list ────────────────────────────────────────────────────

    def _add_user_to_list(self, session: ChatSession, nick: str, is_self: bool = False) -> None:
        for i in range(session.user_list.count()):
            if session.user_list.item(i).data(Qt.ItemDataRole.UserRole) == nick:
                return
        suffix = t("me_suffix") if is_self else ""
        item = QListWidgetItem(f"{nick}{suffix}")
        item.setData(Qt.ItemDataRole.UserRole, nick)
        session.user_list.addItem(item)
        if nick not in session.users:
            session.users.append(nick)
        session.count_label.setText(str(session.user_list.count()))

    def _remove_user_from_list(self, session: ChatSession, nick: str) -> None:
        for i in range(session.user_list.count()):
            if session.user_list.item(i).data(Qt.ItemDataRole.UserRole) == nick:
                session.user_list.takeItem(i)
                if nick in session.users:
                    session.users.remove(nick)
                session.count_label.setText(str(session.user_list.count()))
                return

    # ── Actions ──────────────────────────────────────────────────────

    def _show_protocol_info(self) -> None:
        popup = _ProtocolPopup(self)
        popup.show()
        self._protocol_popup = popup

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_corner_mask()
        rect = self.rect()
        for attr in ("_protocol_popup", "_settings_popup", "_vault_popup", "_new_session_popup", "_qr_popup"):
            popup = getattr(self, attr, None)
            if popup is None:
                continue
            try:
                if popup.isVisible():
                    popup.setGeometry(rect)
            except RuntimeError:
                setattr(self, attr, None)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_corner_mask()

    def _update_corner_mask(self) -> None:
        if self.isMaximized() or self.isFullScreen():
            self.clearMask()
            return
        radius = WINDOW_RADIUS
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _copy_onion(self) -> None:
        # Copy exactly what the label shows: the address without the ".onion"
        # suffix. This is the string another Haze user pastes into "Join", whose
        # field re-appends the suffix — and it matches what the mobile client
        # copies, so the same address round-trips between the two.
        # Tor Browser needs the full "http://<addr>.onion" URL instead; that is
        # what the Tor Browser button (and its clipboard fallback) hands over.
        if self._active:
            addr = (self._active.onion_url or "").removesuffix(".onion")
            QApplication.clipboard().setText(addr)

    def _open_in_tor_browser(self) -> None:
        """Open the session's web UI (onion virtual port 80) in Tor Browser."""
        if not self._active or not self._active.onion_url:
            return
        url = f"http://{self._active.onion_url}"
        argv = _find_tor_browser()
        if argv is None:
            # No Tor Browser found — hand the user a working URL instead of
            # failing silently.
            QApplication.clipboard().setText(url)
            QMessageBox.information(
                self, "Haze",
                t("tor_browser_missing").format(url),
            )
            return
        try:
            subprocess.Popen(
                argv + [url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            log.exception("failed to launch Tor Browser: %s", argv)
            QApplication.clipboard().setText(url)
            QMessageBox.information(
                self, "Haze", t("tor_browser_missing").format(url)
            )

    def _renew_circuit(self) -> None:
        try:
            self.tor.renew_circuit()
        except Exception:
            return
        btn = self._title_bar._renew_btn
        btn.setEnabled(False)
        btn.setText("✓  Renewed")
        if self._active:
            self._append_system(self._active, "⟳ Tor circuit renewed — sessions preserved")
        QTimer.singleShot(2500, lambda: (
            btn.setEnabled(True),
            btn.setText("⟳  Circuit"),
        ))

    def _trigger_panic(self) -> None:
        if not self._active:
            return
        reply = QMessageBox.warning(
            self, t("panic_title"), t("panic_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._append_system(self._active, t("panic_triggered"))
            self._active.bridge.send_panic()
            self._execute_panic_wipe()

    def _show_panic_dialog(self, nick: str) -> None:
        reply = QMessageBox.critical(
            self, t("panic_received_title"),
            t("panic_received").format(nick.upper()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._execute_panic_wipe()

    def _execute_panic_wipe(self) -> None:
        self._quitting = True
        all_msgs: list = []
        for s in self._sessions:
            all_msgs.extend(s.messages)
            try:
                s.bridge.stop()
            except Exception:
                pass
            if s.service_id:
                try:
                    self.tor.remove_service(s.service_id)
                except Exception:
                    pass
        full_wipe(all_msgs, [])
        _cleanup_audio_tmp_files()
        # The log file outlives the process, so it has to go too — otherwise a
        # panic leaves behind a record of when the app ran and what it did.
        wipe_logs()
        self.tor.cleanup()
        os._exit(0)

    # ── Close ────────────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            event.accept()
        else:
            event.ignore()
            self._close_to_tray()

    def quit_app(self) -> None:
        self._quitting = True
        all_msgs: list = []
        for s in self._sessions:
            all_msgs.extend(s.messages)
            try:
                s.bridge.stop()
            except Exception:
                pass
            if s.service_id:
                try:
                    self.tor.remove_service(s.service_id)
                except Exception:
                    pass
        full_wipe(all_msgs, [])
        _cleanup_audio_tmp_files()
        self.tor.cleanup()
        QApplication.quit()


def maze_linux_tag(text: str, size_px: int = 10):
    """The small "for Maze Linux" line beside the app name. It takes the
    surrounding text colour and fades it, so it reads right in every theme."""
    from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel
    from PyQt6.QtCore import Qt
    tag = QLabel(text)
    tag.setObjectName("mazeLinuxTag")
    tag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    tag.setStyleSheet(f"font-size: {size_px}px; background: transparent;")
    fade = QGraphicsOpacityEffect(tag)
    fade.setOpacity(0.55)
    tag.setGraphicsEffect(fade)
    return tag
