"""
Initial dialog: choose Host or Join, enter nickname (+ onion URL if joining).
Language is selected here before the main window opens.
"""

import threading
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget, QProgressBar, QMessageBox,
    QPlainTextEdit, QFrame, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import (
    QPainter, QRadialGradient, QColor, QLinearGradient, QPixmap,
)

from ..tor.controller import TorController
from ..assets import LOGO_PATH, WORDMARK
from ..i18n import t, set_lang, get_lang, LANGUAGES


class _TorWorker(QObject):
    progress = pyqtSignal(str)
    ready    = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, tor: TorController, mode: str) -> None:
        super().__init__()
        self._tor = tor
        self._mode = mode

    def run(self) -> None:
        try:
            def _cb(line: str) -> None:
                if "Bootstrapped" in line:
                    self.progress.emit(line.strip())

            self._tor.start(progress_callback=_cb)

            if self._mode == "host":
                self.progress.emit(t("creating_hs"))
                self._tor.create_hidden_service()

            self.ready.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class _Background(QWidget):
    """Pure-black background with a very subtle radial glow from the top-centre."""

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0))

        cx, cy = self.width() // 2, int(self.height() * 0.28)

        outer = QRadialGradient(cx, cy, self.width() * 0.72)
        outer.setColorAt(0.0, QColor(255, 255, 255, 7))
        outer.setColorAt(0.6, QColor(200, 200, 200, 2))
        outer.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), outer)

        inner = QRadialGradient(cx, cy, self.width() * 0.28)
        inner.setColorAt(0.0, QColor(255, 255, 255, 12))
        inner.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), inner)

        # Bottom darkening vignette
        fade = QLinearGradient(0, int(self.height() * 0.65), 0, self.height())
        fade.setColorAt(0.0, QColor(0, 0, 0, 0))
        fade.setColorAt(1.0, QColor(0, 0, 0, 140))
        p.fillRect(self.rect(), fade)


class SetupDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Haze")
        self.setFixedSize(480, 760)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.mode: str = ""
        self.nick: str = ""
        self.onion_url: str = ""
        self.session_password: str = ""
        self.tor: TorController = TorController()

        self._build_ui()
        self._fade_in()

    # ------------------------------------------------------------------
    # Fade-in
    # ------------------------------------------------------------------

    def _fade_in(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(440)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start()
        self._fade_anim   = anim
        self._fade_effect = effect

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bg = _Background()
        bg_layout = QVBoxLayout(bg)
        bg_layout.setSpacing(0)
        bg_layout.setContentsMargins(52, 40, 52, 40)

        # ── Language selector (top-right) ──
        lang_row = QHBoxLayout()
        lang_row.addStretch()
        self._lang_btns: dict[str, QPushButton] = {}
        for code in LANGUAGES:
            btn = QPushButton(code.upper())
            btn.setFixedSize(38, 26)
            btn.clicked.connect(lambda checked, c=code: self._set_language(c))
            lang_row.addWidget(btn)
            lang_row.addSpacing(4)
            self._lang_btns[code] = btn
        self._refresh_lang_buttons()
        bg_layout.addLayout(lang_row)
        bg_layout.addSpacing(16)

        # ── Logo / title ──
        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if WORDMARK.exists():
            px = QPixmap(str(WORDMARK)).scaledToHeight(
                224, Qt.TransformationMode.SmoothTransformation
            )
            logo_lbl.setPixmap(px)
        elif LOGO_PATH.exists():
            px = QPixmap(str(LOGO_PATH)).scaledToHeight(
                160, Qt.TransformationMode.SmoothTransformation
            )
            logo_lbl.setPixmap(px)
        else:
            logo_lbl.setText("HAZE")
            logo_lbl.setObjectName("logoText")
        bg_layout.addWidget(logo_lbl)
        bg_layout.addSpacing(18)

        self._tagline = QLabel(t("tagline"))
        self._tagline.setObjectName("taglineLabel")
        self._tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bg_layout.addWidget(self._tagline)
        bg_layout.addSpacing(44)

        # ── Mode buttons ──
        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self._host_btn = QPushButton(t("start_chat"))
        self._host_btn.setObjectName("hostBtn")
        self._host_btn.setFixedHeight(52)
        self._join_btn = QPushButton(t("join"))
        self._join_btn.setObjectName("joinBtn")
        self._join_btn.setFixedHeight(52)
        self._host_btn.clicked.connect(lambda: self._select_mode("host"))
        self._join_btn.clicked.connect(lambda: self._select_mode("join"))
        mode_row.addWidget(self._host_btn)
        mode_row.addWidget(self._join_btn)
        bg_layout.addLayout(mode_row)
        bg_layout.addSpacing(30)

        # ── Nickname ──
        self._nick_lbl = QLabel(t("username"))
        self._nick_lbl.setObjectName("sectionTitle")
        bg_layout.addWidget(self._nick_lbl)
        bg_layout.addSpacing(6)
        self._nick_input = QLineEdit()
        self._nick_input.setPlaceholderText(t("placeholder_nick"))
        self._nick_input.setMaxLength(20)
        self._nick_input.setFixedHeight(48)
        bg_layout.addWidget(self._nick_input)

        # ── Onion URL ──
        bg_layout.addSpacing(18)
        self._onion_label = QLabel(t("onion_address"))
        self._onion_label.setObjectName("sectionTitle")
        self._onion_input = QLineEdit()
        self._onion_input.setPlaceholderText(t("placeholder_onion"))
        self._onion_input.setFixedHeight(48)
        bg_layout.addWidget(self._onion_label)
        bg_layout.addSpacing(6)
        bg_layout.addWidget(self._onion_input)
        self._onion_label.hide()
        self._onion_input.hide()

        # ── Session password ──
        bg_layout.addSpacing(18)
        self._pw_label = QLabel(t("session_password"))
        self._pw_label.setObjectName("sectionTitle")
        self._pw_input = QLineEdit()
        self._pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_input.setFixedHeight(48)
        bg_layout.addWidget(self._pw_label)
        bg_layout.addSpacing(6)
        bg_layout.addWidget(self._pw_input)
        self._update_pw_placeholder()

        bg_layout.addSpacing(26)

        # ── Connect button ──
        self._connect_btn = QPushButton(t("connect"))
        self._connect_btn.setObjectName("sendBtn")
        self._connect_btn.setEnabled(False)
        self._connect_btn.setFixedHeight(52)
        self._connect_btn.clicked.connect(self._start_connect)
        bg_layout.addWidget(self._connect_btn)

        bg_layout.addSpacing(14)

        # ── Progress bar ──
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setFixedHeight(2)
        self._progress_bar.hide()
        bg_layout.addWidget(self._progress_bar)
        bg_layout.addSpacing(6)

        # ── Tor log area — transparent, no frame, no box ──
        self._log_area = QPlainTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFixedHeight(110)
        self._log_area.setFrameShape(QFrame.Shape.NoFrame)
        self._log_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._log_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._log_area.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none;"
            " color: #888888; font-family: 'Courier New', monospace; font-size: 10px; }"
        )
        self._log_area.viewport().setStyleSheet("background: transparent;")
        bg_layout.addWidget(self._log_area)
        bg_layout.addSpacing(4)

        # ── One-line status for errors / ready state ──
        self._status_label = QLabel("")
        self._status_label.setObjectName("statusMsg")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setFixedHeight(28)
        bg_layout.addWidget(self._status_label)

        bg_layout.addStretch()

        self._warn = QLabel(t("tor_warning"))
        self._warn.setObjectName("warnLabel")
        self._warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._warn.setWordWrap(True)
        bg_layout.addWidget(self._warn)

        root.addWidget(bg)

        # Host selected by default
        self._select_mode("host")

    # ------------------------------------------------------------------
    # Language switching
    # ------------------------------------------------------------------

    def _set_language(self, code: str) -> None:
        set_lang(code)
        self._refresh_lang_buttons()
        self._retranslate()

    def _refresh_lang_buttons(self) -> None:
        current = get_lang()
        for code, btn in self._lang_btns.items():
            btn.setObjectName("langBtnActive" if code == current else "langBtn")
            btn.setStyle(btn.style())

    def _retranslate(self) -> None:
        """Update all visible text when language changes."""
        self._tagline.setText(t("tagline"))
        self._host_btn.setText(t("start_chat"))
        self._join_btn.setText(t("join"))
        self._nick_lbl.setText(t("username"))
        self._nick_input.setPlaceholderText(t("placeholder_nick"))
        self._onion_label.setText(t("onion_address"))
        self._onion_input.setPlaceholderText(t("placeholder_onion"))
        self._pw_label.setText(t("session_password"))
        self._update_pw_placeholder()
        self._connect_btn.setText(t("connect"))
        self._warn.setText(t("tor_warning"))
        if self._status_label.text() and self._log_area.document().isEmpty():
            self._status_label.setText(t("starting_tor"))

    # ------------------------------------------------------------------
    # Mode selection
    # ------------------------------------------------------------------

    def _update_pw_placeholder(self) -> None:
        if self.mode == "host":
            self._pw_input.setPlaceholderText(t("session_password_host"))
        else:
            self._pw_input.setPlaceholderText(t("session_password_join"))

    def _select_mode(self, mode: str) -> None:
        self.mode = mode
        _active = (
            "QPushButton { background-color: #ffffff; color: #000000; "
            "border: none; border-radius: 12px; "
            "font-size: 14px; font-weight: 700; }"
        )
        _idle = (
            "QPushButton { background-color: #111111; color: #555555; "
            "border: 1px solid #222222; border-radius: 12px; "
            "font-size: 14px; font-weight: 600; }"
        )
        if mode == "host":
            self._host_btn.setStyleSheet(_active)
            self._join_btn.setStyleSheet(_idle)
            self._onion_label.hide()
            self._onion_input.hide()
        else:
            self._join_btn.setStyleSheet(_active)
            self._host_btn.setStyleSheet(_idle)
            self._onion_label.show()
            self._onion_input.show()
        self._update_pw_placeholder()
        self._connect_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Tor startup
    # ------------------------------------------------------------------

    def _start_connect(self) -> None:
        if not self.mode:
            self._status_label.setText(t("select_mode"))
            return

        nick = self._nick_input.text().strip()
        if not nick:
            self._status_label.setText(t("username_empty"))
            return

        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        if not all(c in allowed for c in nick):
            self._status_label.setText(t("username_chars"))
            return

        if self.mode == "join":
            onion = self._onion_input.text().strip()
            if not onion.endswith(".onion"):
                self._status_label.setText(t("onion_required"))
                return
            self.onion_url = onion

        self.nick = nick
        self.session_password = self._pw_input.text().strip()
        self._connect_btn.setEnabled(False)
        self._host_btn.setEnabled(False)
        self._join_btn.setEnabled(False)
        self._progress_bar.show()
        self._status_label.setText(t("starting_tor"))
        self._log_area.clear()

        worker = _TorWorker(self.tor, self.mode)
        worker.progress.connect(self._on_progress)
        worker.ready.connect(self._on_ready)
        worker.error.connect(self._on_error)

        self._worker = worker
        self._thread = threading.Thread(target=worker.run, daemon=True)
        self._thread.start()

    def _on_progress(self, msg: str) -> None:
        self._log_area.appendPlainText(msg)
        # Auto-scroll to latest line
        sb = self._log_area.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._status_label.setText(msg.split(":")[0] if ":" in msg else msg)

    def _on_ready(self) -> None:
        self._progress_bar.hide()
        self._log_area.appendPlainText("✓ Ready.")
        sb = self._log_area.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._status_label.setText(t("ready"))
        if self.mode == "host":
            self.onion_url = self.tor.onion_address or ""
        self.accept()

    def _on_error(self, msg: str) -> None:
        self._progress_bar.hide()
        self._connect_btn.setEnabled(True)
        self._host_btn.setEnabled(True)
        self._join_btn.setEnabled(True)
        self._log_area.appendPlainText(f"✗ {msg}")
        self._status_label.setText(f"{t('error')}: {msg}")
        QMessageBox.critical(self, t("connection_error"), msg)
