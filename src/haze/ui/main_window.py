import asyncio
import math
import os
import threading
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QScrollArea, QSplitter, QFrame, QMessageBox, QApplication,
    QGraphicsOpacityEffect, QSizePolicy, QStyledItemDelegate, QStyle,
    QGraphicsScene, QGraphicsBlurEffect, QGraphicsPixmapItem,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QObject, QPropertyAnimation, QPoint,
    QEasingCurve, QTimer, QParallelAnimationGroup, QRect, QSize, QRectF,
)
from PyQt6.QtGui import (
    QIcon, QCloseEvent, QPixmap, QPainter, QLinearGradient,
    QRadialGradient, QColor, QPen, QBrush, QFont,
)

from ..tor.controller import TorController
from ..network.server import ChatServer
from ..network.client import ChatClient
from ..secure.memory import full_wipe
from ..assets import LOGO_PATH, WORDMARK
from ..i18n import t
from .tray import build_tray


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

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _emit(self, event: dict) -> None:
        self.event_received.emit(event)

    def start_server(self, nick: str, local_port: int) -> None:
        self._server = ChatServer(nick, local_port, self._emit)
        asyncio.run_coroutine_threadsafe(self._server.start(), self._loop)

    def start_client(self, nick: str, onion_host: str, socks_port: int) -> None:
        self._client = ChatClient(nick, onion_host, socks_port, self._emit)
        asyncio.run_coroutine_threadsafe(self._client.connect(), self._loop)

    def send_chat(self, content: str) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(self._server.send_chat(content), self._loop)
        elif self._client:
            asyncio.run_coroutine_threadsafe(self._client.send_chat(content), self._loop)

    def send_panic(self) -> None:
        if self._server:
            asyncio.run_coroutine_threadsafe(self._server.send_panic(), self._loop)
        elif self._client:
            asyncio.run_coroutine_threadsafe(self._client.send_panic(), self._loop)

    def stop(self) -> None:
        futs = []
        if self._server:
            futs.append(asyncio.run_coroutine_threadsafe(self._server.stop(), self._loop))
        if self._client:
            futs.append(asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop))
        # Wait for leave/stop to be sent before killing the loop (max 3 s)
        for f in futs:
            try:
                f.result(timeout=3.0)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)


# ──────────────────────────────────────────────────────────────────────
# Ambient light — animated radial glow background
# ──────────────────────────────────────────────────────────────────────

class _AmbientLight(QWidget):
    """
    Slowly drifting soft radial glows on pure black.
    Used as the background layer of the chat panel.
    The semi-transparent bubble widgets let this show through.
    """

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

        # Base: pure black
        p.fillRect(self.rect(), QColor(0, 0, 0))

        # Primary glow — drifts slowly across the upper half
        cx1 = w * (0.5 + 0.38 * math.sin(self._t * 0.32))
        cy1 = h * (0.38 + 0.22 * math.cos(self._t * 0.25))
        g1 = QRadialGradient(cx1, cy1, w * 0.62)
        g1.setColorAt(0.0,  QColor(255, 255, 255, 18))
        g1.setColorAt(0.35, QColor(210, 215, 225, 7))
        g1.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g1)

        # Secondary glow — counter-drifts through lower half
        cx2 = w * (0.5 - 0.32 * math.cos(self._t * 0.21))
        cy2 = h * (0.65 + 0.20 * math.sin(self._t * 0.28))
        g2 = QRadialGradient(cx2, cy2, w * 0.48)
        g2.setColorAt(0.0,  QColor(190, 195, 210, 10))
        g2.setColorAt(0.5,  QColor(150, 155, 170, 4))
        g2.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g2)

        # Subtle third pulse — very slow, centred
        pulse = 0.5 + 0.5 * math.sin(self._t * 0.15)
        g3 = QRadialGradient(w * 0.5, h * 0.5, w * 0.5)
        g3.setColorAt(0.0,  QColor(255, 255, 255, int(6 * pulse)))
        g3.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g3)


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
                36, Qt.TransformationMode.SmoothTransformation
            )
            logo.setPixmap(px)
        else:
            logo.setText("HAZE")
            logo.setStyleSheet(
                "font-size:15px;font-weight:800;color:#ffffff;letter-spacing:5px;"
            )
        lay.addWidget(logo, 0, _vc)
        lay.addSpacing(8)

        # Protocol badge — clickable, opens info popup
        self._badge = QPushButton(t("protocol_active"))
        self._badge.setObjectName("protocolBadgeActive")
        self._badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._badge.clicked.connect(main_win._show_protocol_info)
        lay.addWidget(self._badge, 0, _vc)

        lay.addStretch()

        # Onion (host only)
        if main_win.mode == "host":
            self._onion_lbl = QLabel(main_win.tor.onion_address or "—")
            self._onion_lbl.setObjectName("onionLabel")
            self._onion_lbl.setFixedHeight(24)
            self._onion_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(self._onion_lbl, 0, _vc)

            copy_btn = QPushButton(t("copy"))
            copy_btn.setObjectName("copyBtn")
            copy_btn.setFixedHeight(24)
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.clicked.connect(main_win._copy_onion)
            lay.addWidget(copy_btn, 0, _vc)
            lay.addSpacing(4)

        # Panic
        panic_btn = QPushButton(t("panic"))
        panic_btn.setObjectName("panicBtn")
        panic_btn.setFixedHeight(24)
        panic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        panic_btn.clicked.connect(main_win._trigger_panic)
        lay.addWidget(panic_btn, 0, _vc)

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
            g.setColorAt(1.0, QColor(0, 0, 0, 220))
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
        self._bot.setGeometry(0, self.height() - 60, w, 60)


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
    g.start()
    widget._sg = g   # keep alive
    widget._sfx = fx


# ──────────────────────────────────────────────────────────────────────
# Blur utility
# ──────────────────────────────────────────────────────────────────────

def _blur_pixmap(src: QPixmap, radius: int = 28) -> QPixmap:
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(src)
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(radius)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    scene.setSceneRect(QRectF(src.rect()))
    out = QPixmap(src.size())
    out.fill(QColor(0, 0, 0, 0))
    p = QPainter(out)
    scene.render(p, QRectF(src.rect()), QRectF(src.rect()))
    p.end()
    return out


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
        if mw.mode == "host" and mw.tor.onion_address:
            addr = mw.tor.onion_address
            short = addr[:20] + "…" + addr[-6:]
            row("Onion Address", short)
        elif mw.mode == "join":
            addr = mw.onion_url
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

class MessageBubble(QWidget):
    def __init__(self, nick: str, content: str, is_me: bool = False) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 3, 20, 3)

        row = QHBoxLayout()

        bubble = QFrame()
        bubble.setObjectName("bubbleMe" if is_me else "bubbleOther")
        bubble.setAutoFillBackground(False)

        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(13, 10, 13, 8)
        inner.setSpacing(3)

        if not is_me:
            n = QLabel(nick.upper())
            n.setObjectName("nickLabel")
            inner.addWidget(n)

        msg = QLabel(content)
        msg.setObjectName("msgText")
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.setMaximumWidth(540)
        inner.addWidget(msg)

        ts = QLabel(datetime.now().strftime("%H:%M"))
        ts.setObjectName("tsLabel")
        ts.setAlignment(
            Qt.AlignmentFlag.AlignRight if is_me else Qt.AlignmentFlag.AlignLeft
        )
        inner.addWidget(ts)

        if is_me:
            row.addStretch()
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch()

        outer.addLayout(row)


class SystemMessage(QWidget):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 10, 28, 10)
        lay.setSpacing(14)
        lay.addWidget(_HRule())
        lbl = QLabel(text)
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
        lbl = QLabel(t("panic_banner").format(nick.upper()))
        lbl.setObjectName("panicBannerText")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.addWidget(lbl)
        lay.addWidget(frame)


class SloganWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 56, 0, 48)
        lay.setSpacing(10)

        if WORDMARK.exists():
            logo = QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            px = QPixmap(str(WORDMARK)).scaledToHeight(
                320, Qt.TransformationMode.SmoothTransformation
            )
            logo.setPixmap(px)
            fx = QGraphicsOpacityEffect(logo)
            fx.setOpacity(0.28)
            logo.setGraphicsEffect(fx)
            logo._fx = fx
            lay.addWidget(logo)
            lay.addSpacing(20)

        lbl = QLabel(t("slogan"))
        lbl.setObjectName("sloganText")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)

        sub = QLabel(t("slogan_sub"))
        sub.setObjectName("sloganSub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)


# ──────────────────────────────────────────────────────────────────────
# Main window
# ──────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(
        self,
        mode: str,
        nick: str,
        tor: TorController,
        onion_url: str = "",
    ) -> None:
        super().__init__()
        self.mode      = mode
        self.nick      = nick
        self.tor       = tor
        self.onion_url = onion_url
        self._quitting = False
        self._messages: list = []

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAutoFillBackground(True)   # paint solid black behind everything

        self._bridge = _NetBridge()
        self._bridge.event_received.connect(self._handle_event)
        self._bridge.start()

        self.setWindowTitle("Haze")
        self.resize(1040, 700)
        self.setMinimumSize(800, 540)

        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self._build_ui()
        self._setup_tray()
        self._fade_in()
        self._start_network()

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
        root = QWidget()
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self._title_bar = _TitleBar(self)
        root_lay.addWidget(self._title_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_chat())
        splitter.setSizes([200, 840])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root_lay.addWidget(splitter)
        QTimer.singleShot(800, self._pulse_badge)

    # ── Sidebar ──────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(200)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setObjectName("sidebarHeader")
        h = QHBoxLayout(hdr)
        h.setContentsMargins(16, 14, 16, 10)
        h.setSpacing(6)
        title = QLabel(t("online"))
        title.setObjectName("sidebarTitle")
        h.addWidget(title)
        h.addStretch()
        self._count_lbl = QLabel("1")
        self._count_lbl.setObjectName("participantCount")
        h.addWidget(self._count_lbl)
        lay.addWidget(hdr)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:rgba(255,255,255,4);")
        lay.addWidget(sep)

        # User list — no horizontal scroll ever
        self._user_list = QListWidget()
        self._user_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._user_list.setMouseTracking(True)
        self._user_list.viewport().setMouseTracking(True)
        self._user_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._user_list.setItemDelegate(_AvatarDelegate(self._user_list))
        lay.addWidget(self._user_list)

        self._add_user(self.nick, is_self=True)
        return panel

    # ── Chat panel ───────────────────────────────────────────────────

    def _build_chat(self) -> _ChatPanel:
        self._chat_panel = _ChatPanel()

        # Scroll area — transparent so ambient light shows through
        self._scroll = _ScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setAutoFillBackground(False)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet("background: transparent;")
        self._scroll.viewport().setStyleSheet("background: transparent;")

        self._msg_container = QWidget()
        self._msg_container.setObjectName("msgArea")
        self._msg_container.setAutoFillBackground(False)
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 28, 0, 28)
        self._msg_layout.setSpacing(2)
        self._msg_layout.addStretch()

        self._scroll.setWidget(self._msg_container)
        self._chat_panel.add_scroll(self._scroll)
        self._chat_panel.add_input(self._build_input_bar())

        self._auto_scroll = False
        # Auto-scroll: fires after layout recomputes — only when enabled
        self._scroll.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: (
                self._scroll.verticalScrollBar().setValue(_max)
                if self._auto_scroll else None
            )
        )

        return self._chat_panel

    def _build_input_bar(self) -> _InputBar:
        bar = _InputBar()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(10)

        self._msg_input = QLineEdit()
        self._msg_input.setObjectName("messageInput")
        self._msg_input.setPlaceholderText(t("type_message"))
        self._msg_input.setFixedHeight(44)
        self._msg_input.returnPressed.connect(self._send_message)
        lay.addWidget(self._msg_input)

        send = QPushButton("↑")
        send.setObjectName("sendBtn")
        send.setFixedSize(44, 44)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.clicked.connect(self._send_message)
        lay.addWidget(send)

        return bar

    # ── Tray ─────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        self._tray = build_tray(self)
        self._tray.show()

    # ── Network ──────────────────────────────────────────────────────

    def _start_network(self) -> None:
        self._append_widget(SloganWidget(), animate=False)
        if self.mode == "host":
            self._bridge.start_server(self.nick, self.tor.local_port)
            self._append_system(t("chat_started"))
        else:
            self._append_system(t("connecting_to").format(self.onion_url))
            self._bridge.start_client(self.nick, self.onion_url, self.tor.socks_port)
        # Enable auto-scroll after initial content is placed
        QTimer.singleShot(500, lambda: setattr(self, "_auto_scroll", True))

    # ── Events ───────────────────────────────────────────────────────

    def _handle_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "chat":
            is_me = event["nick"] == self.nick
            self._append_widget(
                MessageBubble(event["nick"], event["content"], is_me=is_me),
                animate=True,
            )
            self._messages.append(event)
        elif kind == "join":
            self._add_user(event["nick"])
            self._append_system(t("joined").format(event["nick"]))
        elif kind == "leave":
            self._remove_user(event["nick"])
            self._append_system(t("left").format(event["nick"]))
        elif kind == "userlist":
            for u in event.get("users", []):
                if u != self.nick:
                    self._add_user(u)
            self._append_system(t("connected"))
        elif kind == "panic":
            nick = event["nick"]
            self._append_system(t("panic_triggered_by").format(nick))
            self._append_widget(PanicBanner(nick), animate=True)
            self._show_panic_dialog(nick)
        elif kind == "disconnected":
            self._append_system(t("disconnected"))
            self._title_bar.set_badge(t("protocol_lost"), active=False)

    # ── Messaging ────────────────────────────────────────────────────

    def _send_message(self) -> None:
        text = self._msg_input.text().strip()
        if not text:
            return
        self._msg_input.clear()
        self._bridge.send_chat(text)
        if self.mode == "join":
            self._append_widget(
                MessageBubble(self.nick, text, is_me=True), animate=True
            )

    def _append_widget(self, widget: QWidget, animate: bool = False) -> None:
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, widget)
        if animate:
            _slide_in(widget)

    def _append_system(self, text: str) -> None:
        self._append_widget(SystemMessage(text), animate=True)

    # ── User list ────────────────────────────────────────────────────

    def _add_user(self, nick: str, is_self: bool = False) -> None:
        for i in range(self._user_list.count()):
            if self._user_list.item(i).data(Qt.ItemDataRole.UserRole) == nick:
                return
        suffix = t("me_suffix") if is_self else ""
        item = QListWidgetItem(f"{nick}{suffix}")
        item.setData(Qt.ItemDataRole.UserRole, nick)
        self._user_list.addItem(item)
        self._count_lbl.setText(str(self._user_list.count()))

    def _remove_user(self, nick: str) -> None:
        for i in range(self._user_list.count()):
            if self._user_list.item(i).data(Qt.ItemDataRole.UserRole) == nick:
                self._user_list.takeItem(i)
                self._count_lbl.setText(str(self._user_list.count()))
                return

    # ── Actions ──────────────────────────────────────────────────────

    def _show_protocol_info(self) -> None:
        popup = _ProtocolPopup(self)
        popup.show()
        self._protocol_popup = popup

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_protocol_popup") and self._protocol_popup:
            self._protocol_popup.setGeometry(self.rect())

    def _copy_onion(self) -> None:
        QApplication.clipboard().setText(self.tor.onion_address or "")

    def _trigger_panic(self) -> None:
        reply = QMessageBox.warning(
            self, t("panic_title"), t("panic_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._append_system(t("panic_triggered"))
            self._bridge.send_panic()
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
        full_wipe(self._messages, [])
        self._bridge.stop()
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
        full_wipe(self._messages, [])
        self._bridge.stop()
        self.tor.cleanup()
        QApplication.quit()
