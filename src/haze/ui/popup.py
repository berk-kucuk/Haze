"""
Shared base for the app's overlay popups (settings, QR, vault, Tor connection…).

A popup is a full-window blurred-backdrop child widget — not a separate OS
window — so it always looks like part of the frameless, rounded-corner app
window it covers. Lives in its own module (rather than main_window.py, where
these classes originated) so it can be reused by dialogs that open before
MainWindow exists, such as the pre-connection setup screen, without a circular
import between the two.
"""

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QWidget,
)

# Corner radius shared by every top-level app window (MainWindow's
# _RoundedWindowBg, SetupDialog's _Background). Every full-window overlay has
# to clip to it too, or its square corners paint outside the window's rounded
# ones.
WINDOW_RADIUS = 24.0


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


def _clip_to_window_corners(painter: "QPainter", widget: "QWidget") -> None:
    """Clip `painter` to the host window's rounded corners.

    A maximized or fullscreen window has square corners, so the clip is
    skipped there rather than carving rounded notches out of a square window.
    """
    win = widget.window()
    if win.isMaximized() or win.isFullScreen():
        return
    path = QPainterPath()
    path.addRoundedRect(QRectF(widget.rect()), WINDOW_RADIUS, WINDOW_RADIUS)
    painter.setClipPath(path)


class _Popup(QWidget):
    """Full-window blur overlay child of some top-level widget — no separate
    OS window.

    `host` is whatever window the popup should cover — MainWindow once it
    exists, or the frameless SetupDialog before it does. Either way this
    paints a blurred grab of `host` behind a translucent panel, so the popup
    never looks like a separate OS window.
    """

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._panel: QWidget | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(host.rect())
        self._bg = _blur_pixmap(host.grab(), radius=32)
        self.raise_()
        self._fade_in()

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
        self._fx = fx

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _clip_to_window_corners(p, self)
        p.drawPixmap(0, 0, self._bg)
        p.fillRect(self.rect(), QColor(0, 0, 0, 160))

    def mousePressEvent(self, event) -> None:
        if self._panel and not self._panel.geometry().contains(event.pos()):
            self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def _make_panel(self, width: int, height: int) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("protocolPanel")
        panel.setGeometry(
            (self.width() - width) // 2,
            (self.height() - height) // 2,
            width, height,
        )
        self._panel = panel
        return panel

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._panel:
            self._panel.move(
                (self.width() - self._panel.width()) // 2,
                (self.height() - self._panel.height()) // 2,
            )

    @staticmethod
    def _hsep() -> QWidget:
        w = QWidget()
        w.setFixedHeight(1)
        w.setStyleSheet("background: rgba(45,45,50,200);")
        return w
