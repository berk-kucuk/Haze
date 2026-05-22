from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt

from ..assets import LOGO_PATH
from ..i18n import t


def _make_icon() -> QIcon:
    if LOGO_PATH.exists():
        px = QPixmap(str(LOGO_PATH)).scaled(
            64, 64,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(px)

    from PyQt6.QtGui import QPainterPath
    from PyQt6.QtCore import QRect

    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#ffffff"))
    p.setPen(Qt.PenStyle.NoPen)

    path = QPainterPath()
    path.moveTo(12, 40)
    path.arcTo(QRect(12, 10, 40, 40), 180, -180)
    path.lineTo(52, 56)
    path.quadTo(46, 48, 40, 56)
    path.quadTo(34, 48, 28, 56)
    path.quadTo(22, 48, 16, 56)
    path.quadTo(12, 52, 12, 48)
    path.closeSubpath()
    p.drawPath(path)

    p.setBrush(QColor("#000000"))
    p.drawEllipse(22, 26, 8, 10)
    p.drawEllipse(34, 26, 8, 10)
    p.end()
    return QIcon(px)


def build_tray(window) -> QSystemTrayIcon:
    icon = _make_icon()
    tray = QSystemTrayIcon(icon, window)
    tray.setToolTip(t("tray_tooltip"))

    menu = QMenu()

    open_action = menu.addAction(t("tray_open"))
    open_action.triggered.connect(window.show)
    open_action.triggered.connect(window.raise_)
    open_action.triggered.connect(window.activateWindow)

    menu.addSeparator()

    panic_action = menu.addAction(t("tray_panic"))
    panic_action.triggered.connect(window._trigger_panic)

    menu.addSeparator()

    quit_action = menu.addAction(t("tray_quit"))
    quit_action.triggered.connect(window.quit_app)

    tray.setContextMenu(menu)

    def _on_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            window.show()
            window.raise_()
            window.activateWindow()

    tray.activated.connect(_on_activated)
    return tray
