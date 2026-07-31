"""
Tor connection-method picker (direct / vanilla bridge / obfs4 / snowflake).

Lives in its own module because it is needed in two places: the settings popup,
and — more importantly — the setup dialog. A user in a country that filters Tor
never reaches the main window, so the transport has to be switchable before the
first bootstrap ever succeeds.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QPlainTextEdit, QScrollArea,
)
from PyQt6.QtCore import Qt

from ..i18n import t
from ..tor import bridges
from ..storage import settings as _app_settings
from .popup import _Popup

_MODE_LABEL_KEYS = {
    bridges.MODE_DIRECT:    "tor_conn_direct",
    bridges.MODE_VANILLA:   "tor_conn_vanilla",
    bridges.MODE_OBFS4:     "tor_conn_obfs4",
    bridges.MODE_SNOWFLAKE: "tor_conn_snowflake",
}

_MODE_DESC_KEYS = {
    bridges.MODE_DIRECT:    "tor_conn_desc_direct",
    bridges.MODE_VANILLA:   "tor_conn_desc_vanilla",
    bridges.MODE_OBFS4:     "tor_conn_desc_obfs4",
    bridges.MODE_SNOWFLAKE: "tor_conn_desc_snowflake",
}

_MODE_BTN_QSS = (
    "QPushButton{background:rgba(255,255,255,4);color:#606060;"
    "border:1px solid #1e1e20;border-radius:7px;"
    "font-size:11px;font-weight:600;}"
    "QPushButton:checked{background:rgba(255,255,255,10);color:#cccccc;"
    "border-color:#303030;}"
    "QPushButton:hover{background:rgba(255,255,255,7);}"
)

_DESC_QSS = "color:#707070;font-size:10px;background:transparent;"
_HINT_QSS = "color:#4c4c4c;font-size:9px;background:transparent;"
_OK_QSS = "color:#34c759;font-size:9px;font-weight:600;background:transparent;"
_WARN_QSS = "color:#ff9f0a;font-size:9px;font-weight:600;background:transparent;"
_ERR_QSS = "color:#ff453a;font-size:10px;font-weight:600;background:transparent;"

_CUSTOM_QSS = (
    "QPlainTextEdit{background:rgba(255,255,255,4);border:1px solid #1e1e20;"
    "border-radius:7px;color:#b4b4b4;font-family:'JetBrains Mono','Courier New',"
    "monospace;font-size:9px;padding:6px;}"
    "QPlainTextEdit:focus{border-color:#303030;}"
)


class TorConnectionWidget(QWidget):
    """Mode buttons + optional user bridge lines, with live transport status."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected = bridges.normalize_mode(settings.get("tor_bridge_mode"))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # Two rows of two so the labels stay readable in the narrow popup.
        grid = QGridLayout()
        grid.setSpacing(6)
        self._btns: dict[str, QPushButton] = {}
        for i, mode in enumerate(bridges.MODES):
            btn = QPushButton(t(_MODE_LABEL_KEYS[mode]))
            btn.setCheckable(True)
            btn.setChecked(mode == self._selected)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_MODE_BTN_QSS)
            btn.clicked.connect(lambda _=False, m=mode: self._select(m))
            grid.addWidget(btn, i // 2, i % 2)
            self._btns[mode] = btn
        lay.addLayout(grid)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet(_DESC_QSS)
        lay.addWidget(self._desc)

        # ── Custom bridge lines ──
        self._custom_box = QWidget()
        cb_lay = QVBoxLayout(self._custom_box)
        cb_lay.setContentsMargins(0, 0, 0, 0)
        cb_lay.setSpacing(5)

        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        custom_lbl = QLabel(t("tor_conn_custom"))
        custom_lbl.setObjectName("popupSectionLabel")
        head_row.addWidget(custom_lbl)
        self._custom_req = QLabel()
        self._custom_req.setStyleSheet(_HINT_QSS)
        head_row.addWidget(self._custom_req)
        head_row.addStretch()
        cb_lay.addLayout(head_row)

        self._custom = QPlainTextEdit(settings.get("tor_bridges_custom", "") or "")
        self._custom.setFixedHeight(74)
        self._custom.setStyleSheet(_CUSTOM_QSS)
        self._custom.setPlaceholderText(
            "obfs4 192.0.2.1:443 FINGERPRINT cert=… iat-mode=0"
        )
        self._custom.textChanged.connect(self._refresh_status)
        cb_lay.addWidget(self._custom)

        hint = QLabel(t("tor_conn_custom_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(_HINT_QSS)
        cb_lay.addWidget(hint)
        lay.addWidget(self._custom_box)

        self._status = QLabel()
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setStyleSheet(_ERR_QSS)
        self._error.hide()
        lay.addWidget(self._error)

        self._select(self._selected)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def mode(self) -> str:
        return self._selected

    def custom_text(self) -> str:
        return self._custom.toPlainText().strip()

    def apply_to(self, settings: dict) -> None:
        settings["tor_bridge_mode"] = self._selected
        settings["tor_bridges_custom"] = self.custom_text()

    def validate(self) -> str | None:
        """Error message to show, or None when the selection is usable.

        Only checks what the user can fix here — a missing transport binary is
        surfaced as status text instead, since installing it is a separate step.
        """
        if not bridges.uses_bridges(self._selected):
            return None
        if not bridges.effective_bridge_lines(self._selected, self.custom_text()):
            return t("tor_conn_no_lines")
        try:
            bridges.torrc_options(self._selected, self.custom_text())
        except bridges.BridgeConfigError as exc:
            # Missing binary is reported by _refresh_status; anything else here
            # is a malformed line the user pasted.
            if bridges.find_transport_binary(self._selected) or not \
                    bridges.needs_transport_binary(self._selected):
                return str(exc)
        return None

    def show_error(self, msg: str | None) -> None:
        self._error.setText(msg or "")
        self._error.setVisible(bool(msg))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _select(self, mode: str) -> None:
        self._selected = mode
        for m, btn in self._btns.items():
            btn.setChecked(m == mode)
        self._desc.setText(t(_MODE_DESC_KEYS[mode]))
        self._custom_box.setVisible(bridges.uses_bridges(mode))
        self._custom_req.setText(
            t("tor_conn_custom_required")
            if not bridges.BUILTIN_BRIDGES.get(mode)
            else t("tor_conn_custom_optional")
        )
        self.show_error(None)
        self._refresh_status()

    def _refresh_status(self) -> None:
        mode = self._selected
        if not bridges.uses_bridges(mode):
            self._status.hide()
            return

        parts: list[str] = []
        qss = _OK_QSS

        if bridges.needs_transport_binary(mode):
            names = bridges.transport_binary_names(mode)
            if bridges.find_transport_binary(mode):
                parts.append(t("tor_conn_binary_ok").format(names))
            else:
                parts.append(
                    t("tor_conn_binary_missing").format(
                        names, bridges.INSTALL_HINTS.get(mode, "")
                    )
                )
                qss = _WARN_QSS

        if not bridges.parse_bridge_lines(self.custom_text()):
            builtin = bridges.BUILTIN_BRIDGES.get(mode, ())
            if builtin:
                parts.append(t("tor_conn_builtin").format(len(builtin)))

        self._status.setText("\n".join(parts))
        self._status.setStyleSheet(qss)
        self._status.setVisible(bool(parts))


class _TorConnectionPopup(_Popup):
    """Tor connection method popup — the same blurred-overlay style as the
    Settings, QR and Vault popups, rather than a plain OS dialog window.

    `host` is whichever top-level window is covering the screen when this
    opens: the pre-connection SetupDialog (a user on a filtered network needs
    the transport switchable before the first bootstrap ever succeeds, and
    that screen exists before MainWindow does), or MainWindow itself when
    reached from Settings. Saves straight to settings.json on Save, so the
    choice survives the inevitable retry after a failed bootstrap.
    """

    def __init__(self, host: QWidget, settings: dict) -> None:
        super().__init__(host)
        self._settings = settings

        panel = self._make_panel(420, 600)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Title row
        title_row = QWidget()
        title_row.setFixedHeight(52)
        tr_lay = QHBoxLayout(title_row)
        tr_lay.setContentsMargins(24, 0, 16, 0)
        title_lbl = QLabel(t("tor_connection"))
        title_lbl.setObjectName("popupTitle")
        tr_lay.addWidget(title_lbl)
        tr_lay.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("popupCloseBtn")
        close_btn.clicked.connect(self.close)
        tr_lay.addWidget(close_btn)
        lay.addWidget(title_row)
        lay.addWidget(self._hsep())

        # Scrollable body — the custom-bridge box appearing/disappearing must
        # not be able to push the Save button off the bottom of the panel.
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

        self._widget = TorConnectionWidget(settings)
        il.addWidget(self._widget)

        note = QLabel(t("tor_conn_slow_note"))
        note.setWordWrap(True)
        note.setStyleSheet(_HINT_QSS)
        il.addWidget(note)
        il.addStretch()

        # Pinned outside the scroll area so it is always reachable.
        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(28, 10, 28, 20)
        fl.setSpacing(10)
        cancel = QPushButton(t("close"))
        cancel.setObjectName("copyBtn")
        cancel.setFixedHeight(38)
        cancel.clicked.connect(self.close)
        fl.addWidget(cancel)
        save = QPushButton(t("save"))
        save.setObjectName("sendBtn")
        save.setFixedHeight(38)
        save.clicked.connect(self._save)
        fl.addWidget(save)
        lay.addWidget(footer)

    def _save(self) -> None:
        error = self._widget.validate()
        if error:
            self._widget.show_error(error)
            return
        self._widget.apply_to(self._settings)
        _app_settings.save(self._settings)
        self.close()
