DARK_QSS = """
* { outline: none; }

QWidget {
    background-color: #000000;
    color: #e8e8e8;
    font-family: "Inter", "SF Pro Text", "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
    selection-background-color: #303030;
    selection-color: #ffffff;
    border: none;
}

QMainWindow { background-color: #000000; }

/* ── Title bar ── */
#titleBar {
    background-color: rgba(4, 4, 6, 255);
    border-bottom: 1px solid #141414;
    min-height: 42px;
    max-height: 42px;
}

QPushButton#onionLabel {
    font-size: 9px;
    color: #c0c0c0;
    font-family: "JetBrains Mono", "Fira Code", monospace;
    padding: 0px 10px;
    background: rgba(10,10,12,220);
    border: 1px solid #303030;
    border-radius: 5px;
    min-height: 24px;
    max-height: 24px;
    text-align: left;
}
QPushButton#onionLabel:hover {
    color: #ffffff;
    border-color: #484848;
    background: rgba(22,22,26,220);
}
QPushButton#onionLabel:pressed {
    color: #ffffff;
    background: rgba(32,32,38,220);
}

QPushButton#copyBtn {
    background: transparent;
    border: 1px solid #222222;
    color: #808080;
    padding: 2px 10px;
    font-size: 11px;
    border-radius: 5px;
    min-height: 24px;
}
QPushButton#copyBtn:hover { color: #dddddd; border-color: #404040; background: rgba(18,18,18,200); }

QPushButton#panicBtn {
    background-color: rgba(14,0,0,240);
    color: #ff3b30;
    border: 1px solid #280000;
    border-radius: 6px;
    padding: 3px 12px;
    font-weight: 700;
    font-size: 10px;
    letter-spacing: 2px;
    min-height: 24px;
}
QPushButton#panicBtn:hover { background: rgba(28,0,0,240); border-color: #ff3b30; color: #ff6b61; }
QPushButton#panicBtn:pressed { background: #ff3b30; color: #000000; }

/* Window control buttons */
#winBtn {
    background: transparent;
    color: #686868;
    border: none;
    border-radius: 5px;
    font-size: 12px;
    min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px;
}
#winBtn:hover { background: rgba(255,255,255,10); color: #cccccc; }
#winBtnClose:hover { background: rgba(255,40,40,18); color: #ff5050; }

/* ── Sidebar (participants) ── */
#sidebar {
    background-color: #000000;
    border-right: 1px solid #101010;
    min-width: 200px;
    max-width: 200px;
}
#sidebarHeader { background: transparent; }
#sidebarTitle {
    color: #909090;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}
#participantCount {
    color: #888888;
    font-size: 10px;
    font-weight: 600;
}

QListWidget {
    background: transparent;
    border: none;
    padding: 4px 0 8px;
}
QListWidget::item {
    padding: 0 8px 0 44px;
    min-height: 44px;
    border-radius: 8px;
    color: #b8b8b8;
    font-size: 12px;
    margin: 1px 8px;
    background: transparent;
}
QListWidget::item:selected { background: rgba(255,255,255,8); color: #ffffff; }
QListWidget::item:hover    { background: rgba(255,255,255,4); color: #e0e0e0; }

/* ── Scroll ── */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

QScrollBar:vertical {
    background: transparent;
    width: 3px; margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,16);
    border-radius: 2px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,28); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* ── Message area ── */
#msgArea { background: transparent; }

#bubbleMe {
    background-color: rgba(30, 30, 32, 215);
    border: 1px solid rgba(65, 65, 68, 120);
    border-top-color: rgba(75, 75, 78, 140);
    border-radius: 18px 18px 4px 18px;
    max-width: 540px;
}
#bubbleOther {
    background-color: rgba(14, 14, 16, 210);
    border: 1px solid rgba(42, 42, 46, 100);
    border-top-color: rgba(52, 52, 56, 120);
    border-radius: 18px 18px 18px 4px;
    max-width: 540px;
}
#nickLabel {
    font-size: 10px;
    font-weight: 700;
    color: #909090;
    letter-spacing: 0.8px;
    background: transparent;
}
#msgText {
    color: #eeeeee;
    font-size: 13px;
    background: transparent;
}
#tsLabel {
    font-size: 10px;
    color: #9a9a9a;
    background: transparent;
}

/* ── System messages ── */
#systemMsg {
    color: #9a9a9a;
    font-size: 11px;
    font-style: italic;
    background: transparent;
}

/* ── Input bar ── */
#inputBar {
    background-color: rgba(3, 3, 5, 240);
    border-top: 1px solid rgba(24, 24, 24, 220);
    padding: 12px 18px 16px;
}
QLineEdit#messageInput {
    background-color: rgba(14, 14, 16, 220);
    border: 1px solid rgba(38, 38, 40, 180);
    border-radius: 22px;
    padding: 12px 20px;
    color: #f0f0f0;
    font-size: 13px;
}
QLineEdit#messageInput:focus {
    border-color: rgba(70, 70, 74, 200);
    background-color: rgba(18, 18, 20, 230);
}
QLineEdit#messageInput::placeholder { color: #505050; }

QPushButton#sendBtn {
    background-color: #ffffff;
    color: #000000;
    border: none;
    border-radius: 22px;
    font-size: 17px;
    font-weight: 700;
}
QPushButton#sendBtn:hover  { background-color: #e0e0e0; }
QPushButton#sendBtn:pressed{ background-color: #b8b8b8; }

/* ── Panic banner ── */
#panicBanner {
    background-color: rgba(22, 0, 0, 230);
    border: 1px solid rgba(80, 0, 0, 180);
    border-top-color: rgba(100, 0, 0, 200);
    border-radius: 14px;
    padding: 16px 20px;
}
#panicBannerText {
    color: #ff3b30;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.5px;
    background: transparent;
}

/* ── Slogan ── */
#sloganText {
    font-size: 14px;
    font-style: italic;
    color: #888888;
    letter-spacing: 0.5px;
    background: transparent;
}
#sloganSub {
    font-size: 10px;
    color: #787878;
    letter-spacing: 3px;
    background: transparent;
}

/* ── Setup dialog ── */
#logoText {
    font-size: 44px; font-weight: 800;
    color: #ffffff; letter-spacing: 14px;
}
#taglineLabel { font-size: 10px; color: #777777; letter-spacing: 3px; }
#sectionTitle  { font-size: 10px; font-weight: 700; color: #aaaaaa; letter-spacing: 2px; }
#warnLabel     { font-size: 10px; color: #777777; }
#statusMsg     { font-size: 11px; color: #aaaaaa; }

QPushButton#hostBtn {
    font-size: 14px; font-weight: 600; padding: 14px 0; border-radius: 12px;
    background-color: #ffffff; color: #000000; border: none;
}
QPushButton#hostBtn:hover  { background-color: #e8e8e8; }
QPushButton#hostBtn:pressed{ background-color: #cccccc; }

QPushButton#joinBtn {
    font-size: 14px; font-weight: 600; padding: 14px 0; border-radius: 12px;
    background-color: #000000; color: #ffffff; border: 1px solid #2e2e2e;
}
QPushButton#joinBtn:hover  { background-color: #141414; border-color: #484848; }
QPushButton#joinBtn:pressed{ background-color: #080808; }

QPushButton#langBtn {
    background: transparent; border: 1px solid #222222;
    color: #666666; font-size: 11px; font-weight: 700;
    letter-spacing: 1px; padding: 3px 9px; border-radius: 6px;
}
QPushButton#langBtn:hover { color: #aaaaaa; border-color: #404040; }
QPushButton#langBtnActive {
    background: #141414; border: 1px solid #404040;
    color: #ffffff; font-size: 11px; font-weight: 700;
    letter-spacing: 1px; padding: 3px 9px; border-radius: 6px;
}

QLineEdit {
    background-color: #0d0d0d; border: 1px solid #242424;
    border-radius: 10px; padding: 10px 14px; color: #ffffff; font-size: 13px;
}
QLineEdit:focus { border-color: #484848; background-color: #111111; }
QLineEdit::placeholder { color: #505050; }

QProgressBar {
    background-color: #0d0d0d; border: none; border-radius: 2px; max-height: 2px;
}
QProgressBar::chunk { background-color: #ffffff; border-radius: 2px; }

/* ── Splitter ── */
QSplitter::handle:horizontal { background-color: #0c0c0c; width: 1px; }

/* ── Menu ── */
QMenu {
    background-color: rgba(12,12,14,250); border: 1px solid #222222;
    border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 9px 20px; border-radius: 6px; color: #d8d8d8; font-size: 13px; }
QMenu::item:selected { background-color: rgba(255,255,255,10); color: #ffffff; }
QMenu::separator { height: 1px; background: #181818; margin: 4px 8px; }

QToolTip {
    background-color: rgba(16,16,18,250); color: #c8c8c8;
    border: 1px solid #242424; border-radius: 6px;
    padding: 5px 10px; font-size: 11px;
}

QMessageBox { background-color: #0d0d0d; }
QMessageBox QLabel { color: #dddddd; font-size: 13px; }
QMessageBox QPushButton { min-width: 80px; }

/* ── Protocol badge ── */
QPushButton#protocolBadgeActive {
    font-size: 9px; font-weight: 700; color: #34c759;
    letter-spacing: 1.5px; padding: 2px 7px;
    border: 1px solid #0a2e14; border-radius: 6px;
    background-color: #020905;
}
QPushButton#protocolBadgeActive:hover { background-color: #041510; border-color: #1a5e2c; }
QPushButton#protocolBadge {
    font-size: 9px; font-weight: 700; color: #686868;
    letter-spacing: 1.5px; padding: 2px 7px;
    border: 1px solid #1e1e1e; border-radius: 6px;
    background-color: #080808;
}
QPushButton#protocolBadge:hover { color: #888888; border-color: #303030; }

/* ── Popup panels ── */
#protocolPanel {
    background-color: rgba(7, 7, 9, 248);
    border: 1px solid rgba(52, 52, 58, 255);
    border-top-color: rgba(68, 68, 74, 255);
    border-radius: 20px;
}
#popupTitle {
    font-size: 11px; font-weight: 800; color: #ffffff;
    letter-spacing: 3px; background: transparent;
}
#popupEncBadge {
    font-size: 9px; font-weight: 700; color: #34c759;
    letter-spacing: 1.5px; padding: 2px 8px;
    border: 1px solid #0a2e14; border-radius: 6px; background-color: #020905;
}
#popupSectionLabel {
    font-size: 9px; font-weight: 700; color: #909090;
    letter-spacing: 2.5px; background: transparent;
}
#popupKey   { font-size: 12px; color: #aaaaaa; background: transparent; }
#popupValue { font-size: 12px; color: #cccccc; font-weight: 600; background: transparent; }
#popupValueGreen { font-size: 12px; color: #34c759; font-weight: 600; background: transparent; }
QPushButton#popupCloseBtn {
    background: rgba(22, 22, 26, 200); color: #686868;
    border: 1px solid #2e2e32; border-radius: 14px; font-size: 13px;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
}
QPushButton#popupCloseBtn:hover { color: #cccccc; border-color: #484848; background: rgba(38,38,42,220); }

/* ── Session sidebar (vertical, width set programmatically) ── */
#sessionSidebar {
    background-color: rgba(4, 4, 6, 255);
    border-right: 1px solid #111111;
}
QPushButton#sessionTab {
    background: transparent; color: #686868;
    border: none; border-radius: 6px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
    padding: 5px 10px; min-height: 32px; text-align: left;
}
QPushButton#sessionTab:hover { color: #aaaaaa; background: rgba(255,255,255,6); }
QPushButton#sessionTabActive {
    background: rgba(255,255,255,12); color: #eeeeee;
    border: none; border-radius: 6px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
    padding: 5px 10px; min-height: 32px; text-align: left;
}
QPushButton#addSessionBtn {
    background: rgba(255,255,255,5); color: #686868;
    border: 1px solid #242424; border-radius: 6px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
    padding: 5px 10px; min-height: 32px; text-align: left;
}
QPushButton#addSessionBtn:hover { color: #aaaaaa; border-color: #404040; background: rgba(255,255,255,9); }
QPushButton#sidebarCollapseBtn {
    background: transparent; color: #585858;
    border: none; border-radius: 5px;
    font-size: 13px; font-weight: 700; padding: 0;
    min-height: 24px; max-height: 24px;
}
QPushButton#sidebarCollapseBtn:hover { color: #aaaaaa; background: rgba(255,255,255,7); }

/* ── Mode selector buttons (new-session popup) ── */
QPushButton#modeBtn {
    font-size: 12px; font-weight: 700; letter-spacing: 0.5px;
    padding: 0; border-radius: 10px;
    background-color: #0c0c0c; color: #666666;
    border: 1px solid #242424; min-height: 42px;
}
QPushButton#modeBtn:hover { background-color: #141414; color: #aaaaaa; border-color: #383838; }
QPushButton#modeBtn:checked { background-color: #1e1e1e; color: #ffffff; border-color: #505050; }
QPushButton#modeBtn:pressed { background-color: #282828; }

/* ── Settings / Vault button (title bar) ── */
QPushButton#settingsBtn {
    background: transparent; color: #686868;
    border: 1px solid #222222; border-radius: 6px; font-size: 14px;
    min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
}
QPushButton#settingsBtn:hover { color: #cccccc; border-color: #404040; background: rgba(255,255,255,6); }

/* ── Vault button (sidebar) ── */
QPushButton#vaultBtn {
    background: rgba(255,255,255,4); color: #787878;
    border: 1px solid #1c1c1c; border-radius: 8px;
    font-size: 11px; font-weight: 600; letter-spacing: 1px;
    padding: 8px 0; margin: 8px 12px;
}
QPushButton#vaultBtn:hover { background: rgba(255,255,255,8); color: #aaaaaa; border-color: #303030; }

/* ── Attach file button ── */
QPushButton#attachBtn {
    background-color: rgba(20, 20, 22, 200); color: #787878;
    border: 1px solid rgba(36, 36, 38, 180); border-radius: 22px;
    font-size: 20px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
}
QPushButton#attachBtn:hover { background-color: rgba(32, 32, 36, 220); color: #cccccc; }

/* ── File download button ── */
QPushButton#fileDownloadBtn {
    background: rgba(255,255,255,10); color: #cccccc;
    border: 1px solid rgba(255,255,255,14); border-radius: 8px;
    font-size: 11px; padding: 5px 14px; max-width: 200px;
}
QPushButton#fileDownloadBtn:hover { background: rgba(255,255,255,16); color: #ffffff; }
QPushButton#fileDownloadBtn:disabled { color: #444444; border-color: rgba(255,255,255,5); }

/* ── Settings / Vault dialog ── */
#settingsPanel, #vaultPanel {
    background-color: rgba(7, 7, 9, 252);
    border: 1px solid rgba(52, 52, 58, 255);
    border-top-color: rgba(68, 68, 74, 255);
    border-radius: 20px;
}
QCheckBox { color: #cccccc; font-size: 13px; spacing: 10px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid #383838; background: #0d0d0d;
}
QCheckBox::indicator:checked { background: #ffffff; border-color: #ffffff; }
QCheckBox::indicator:disabled { border-color: #222222; background: #080808; }

/* ── Typing indicator ── */
#typingBar { background: transparent; padding: 2px 24px 6px 24px; min-height: 22px; }
QLabel#typingLabel { color: #686868; font-size: 10px; font-style: italic; letter-spacing: 0.5px; background: transparent; }

/* ── Code block ── */
#codeBlock { background: rgba(255,255,255,5); border: 1px solid rgba(255,255,255,10); border-radius: 6px; margin: 3px 0; }
QLabel#codeText { font-family: "Fira Code", "JetBrains Mono", "Courier New", monospace; font-size: 11px; color: #a8e6a0; background: transparent; }

/* ── Search bar ── */
#searchBar { background: rgba(6, 6, 8, 230); border-bottom: 1px solid #141414; padding: 6px 16px; }
QLineEdit#searchInput {
    background: rgba(255,255,255,6); border: 1px solid #242428;
    border-radius: 8px; color: #c8c8c8; font-size: 12px;
    padding: 5px 12px; min-height: 30px;
}
QLabel#searchCounter { color: #686868; font-size: 10px; min-width: 40px; background: transparent; }
QPushButton#searchNavBtn {
    background: transparent; color: #686868; border: none; font-size: 14px;
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; border-radius: 4px;
}
QPushButton#searchNavBtn:hover { color: #cccccc; background: rgba(255,255,255,6); }
QPushButton#searchCloseBtn {
    background: transparent; color: #585858; border: none; font-size: 12px;
    min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
}
QPushButton#searchCloseBtn:hover { color: #aaaaaa; }

/* ── Message highlight ── */
QFrame#bubbleHighlight {
    border: 1px solid rgba(255, 230, 100, 60); background: rgba(255, 230, 100, 8); border-radius: 10px;
}

/* ── Voice record button ── */
QPushButton#voiceBtn {
    background-color: rgba(20, 20, 22, 200); color: #787878;
    border: 1px solid rgba(36, 36, 38, 180); border-radius: 22px; font-size: 16px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
}
QPushButton#voiceBtn:hover { background-color: rgba(32, 32, 36, 220); color: #aaaaaa; }
QPushButton#voiceBtnRecording {
    background-color: rgba(180, 30, 30, 200); color: #ff5555;
    border: 1px solid rgba(220, 40, 40, 180); border-radius: 22px; font-size: 16px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
}

/* ── QR popup panel ── */
#qrPanel {
    background-color: rgba(7, 7, 9, 252);
    border: 1px solid rgba(52, 52, 58, 255);
    border-top-color: rgba(68, 68, 74, 255);
    border-radius: 20px;
}

/* ── Disappearing timer badge ── */
QLabel#disappearBadge {
    color: #686868; font-size: 9px; font-weight: 600; letter-spacing: 0.5px;
    background: transparent; padding: 1px 4px;
    border: 1px solid #242426; border-radius: 4px;
}
"""


# ── Themes ────────────────────────────────────────────────────────────────────
# Each theme's qss is appended after DARK_QSS (later rules override earlier).

THEMES: dict[str, dict] = {

    # ── 1. Haze — pure black / white, high contrast (default) ─────────────
    "haze": {
        "name": "Haze",
        "swatch": "#c8c8c8",
        "qss": "",          # DARK_QSS is already the Haze theme
    },

    # ── 2. Hacker — matrix green on pure black ─────────────────────────────
    "hacker": {
        "name": "Hacker",
        "swatch": "#00ff41",
        "qss": """
QWidget { background-color: #000000; color: #00e83a;
          font-family: "JetBrains Mono", "Fira Code", "Courier New", monospace;
          font-size: 13px;
          selection-background-color: #003a14; selection-color: #00ff41; }
QMainWindow { background: #000000; }

#titleBar { background-color: rgba(0,6,0,255); border-bottom-color: #001600; }
#sessionSidebar { background-color: rgba(0,5,0,255); border-right-color: #001000; }
#sidebar { background-color: #000000; border-right-color: #001200; }
#sidebarTitle { color: #006a20; }
#participantCount { color: #005518; }

QListWidget::item { color: #007828; }
QListWidget::item:selected { background: rgba(0,255,65,7); color: #00ff41; }
QListWidget::item:hover    { background: rgba(0,255,65,4); color: #00cc34; }

QScrollBar::handle:vertical { background: rgba(0,255,65,15); }
QScrollBar::handle:vertical:hover { background: rgba(0,255,65,28); }

#bubbleMe    { background-color: rgba(0,18,5,215); border-color: rgba(0,200,54,85); border-top-color: rgba(0,220,62,105); }
#bubbleOther { background-color: rgba(0,10,2,210); border-color: rgba(0,100,30,75); }
#nickLabel  { color: #007828; }
#msgText    { color: #00e038; font-family: "JetBrains Mono","Fira Code",monospace; }
#tsLabel    { color: #005518; }
#systemMsg  { color: #005518; font-family: "JetBrains Mono","Fira Code",monospace; }

#inputBar { background-color: rgba(0,6,0,240); border-top-color: rgba(0,22,6,220); }
QLineEdit#messageInput { background-color: rgba(0,10,2,220); border-color: rgba(0,48,14,180); color: #00ff41;
                         font-family: "JetBrains Mono","Fira Code",monospace; }
QLineEdit#messageInput:focus { border-color: rgba(0,210,64,150); background-color: rgba(0,14,3,230); }
QLineEdit#messageInput::placeholder { color: #002a0a; }

QPushButton#sendBtn         { background-color: #009938; color: #00ff41; }
QPushButton#sendBtn:hover   { background-color: #00bb44; }
QPushButton#sendBtn:pressed { background-color: #007728; }

QLineEdit { background-color: #000e00; border-color: #002800; color: #00ff41;
            font-family: "JetBrains Mono","Fira Code",monospace; }
QLineEdit:focus { border-color: #00aa34; background-color: #001400; }
QLineEdit::placeholder { color: #002800; }

QPushButton#sessionTab         { color: #004818; }
QPushButton#sessionTab:hover   { color: #00aa34; background: rgba(0,255,65,5); }
QPushButton#sessionTabActive   { background: rgba(0,255,65,11); color: #00ee3c; }
QPushButton#addSessionBtn      { color: #005a1c; border-color: #002200; background: rgba(0,255,65,4); }
QPushButton#addSessionBtn:hover { color: #00cc44; border-color: #004800; background: rgba(0,255,65,8); }
QPushButton#sidebarCollapseBtn { color: #003814; }
QPushButton#sidebarCollapseBtn:hover { color: #00bb44; background: rgba(0,255,65,6); }

#winBtn { color: #004818; }
#winBtn:hover { background: rgba(0,255,65,7); color: #00cc44; }
#winBtnClose:hover { background: rgba(255,40,40,14); color: #ff5050; }

QPushButton#onionLabel { color: #00aa34; background: rgba(0,10,2,220); border-color: #003200;
                         font-family: "JetBrains Mono",monospace; }
QPushButton#onionLabel:hover { color: #00ff41; border-color: #007800; }
QPushButton#copyBtn { color: #005a1c; border-color: #002200; }
QPushButton#copyBtn:hover { color: #00cc44; border-color: #006600; }

QPushButton#settingsBtn { color: #004818; border-color: #001c08; }
QPushButton#settingsBtn:hover { color: #00cc44; border-color: #005500; }

QPushButton#protocolBadgeActive { background: #000e04; border-color: #005a1c; color: #00cc44; }
QPushButton#protocolBadge       { background: #000800; border-color: #001c08; color: #004818; }
QPushButton#protocolBadge:hover { color: #00aa34; border-color: #004400; }

#protocolPanel { background-color: rgba(0,7,2,252); border-color: rgba(0,62,20,255); border-top-color: rgba(0,80,26,255); }
#settingsPanel, #vaultPanel { background-color: rgba(0,7,2,252); border-color: rgba(0,62,20,255); border-top-color: rgba(0,80,26,255); }
#qrPanel { background-color: rgba(0,7,2,252); border-color: rgba(0,62,20,255); }

#popupTitle { color: #00ff41; font-family: "JetBrains Mono",monospace; }
#popupSectionLabel { color: #007828; }
#popupKey   { color: #006622; }
#popupValue { color: #00cc44; }
#popupValueGreen { color: #00ff41; }
QPushButton#popupCloseBtn { background: rgba(0,14,4,200); color: #005a1c; border-color: #002400; }
QPushButton#popupCloseBtn:hover { color: #00cc44; border-color: #007700; }

QMenu { background-color: rgba(0,8,2,250); border-color: #003200; }
QMenu::item { color: #00cc44; }
QMenu::item:selected { background: rgba(0,255,65,9); color: #00ff41; }
QMenu::separator { background: #002200; }

QToolTip { background-color: rgba(0,10,3,250); color: #00cc44; border-color: #003200; }
QSplitter::handle:horizontal { background-color: #001400; }

QPushButton#modeBtn         { background-color: #000e00; color: #005a1c; border-color: #002200; }
QPushButton#modeBtn:hover   { background-color: #001600; color: #00aa34; border-color: #004800; }
QPushButton#modeBtn:checked { background-color: #002c00; color: #00ff41; border-color: #007700; }

QPushButton#vaultBtn { color: #006622; border-color: #002200; background: rgba(0,255,65,4); }
QPushButton#attachBtn { background-color: rgba(0,14,4,200); color: #005a1c; border-color: rgba(0,40,12,180); }
QPushButton#attachBtn:hover { background-color: rgba(0,20,6,220); color: #00cc44; }
QPushButton#voiceBtn { background-color: rgba(0,14,4,200); color: #005a1c; border-color: rgba(0,40,12,180); }
QPushButton#voiceBtn:hover { background-color: rgba(0,20,6,220); color: #00cc44; }
QPushButton#voiceBtnRecording { background-color: rgba(160,30,30,200); color: #ff5555; border-color: rgba(200,40,40,180); }
QPushButton#fileDownloadBtn { background: rgba(0,255,65,8); color: #00cc44; border-color: rgba(0,255,65,14); }
QPushButton#fileDownloadBtn:hover { background: rgba(0,255,65,14); color: #00ff41; }

QCheckBox { color: #00aa34; }
QCheckBox::indicator { border-color: #003200; background: #000e00; }
QCheckBox::indicator:checked { background: #00aa34; border-color: #00cc44; }

QLabel#typingLabel { color: #004818; font-style: italic; }
QLabel#searchCounter { color: #005a1c; }
QPushButton#searchNavBtn { color: #005a1c; }
QPushButton#searchNavBtn:hover { color: #00cc44; background: rgba(0,255,65,6); }
QPushButton#searchCloseBtn { color: #004818; }
QPushButton#searchCloseBtn:hover { color: #00cc44; }
QLineEdit#searchInput { background: rgba(0,255,65,4); border-color: #002800; color: #00cc44; }

#codeBlock { background: rgba(0,255,65,5); border-color: rgba(0,255,65,14); }
QLabel#codeText { color: #00ff41; }

QLabel#disappearBadge { color: #005a1c; border-color: #002800; }
QFrame#bubbleHighlight { border-color: rgba(0,255,65,50); background: rgba(0,255,65,7); }

#sloganText { color: #006622; font-family: "JetBrains Mono",monospace; }
#sloganSub  { color: #005518; font-family: "JetBrains Mono",monospace; }

#taglineLabel { color: #006622; font-family: "JetBrains Mono",monospace; }
#sectionTitle { color: #00aa34; font-family: "JetBrains Mono",monospace; }
#warnLabel    { color: #006622; }
#statusMsg    { color: #00aa34; }
#logoText     { color: #00ff41; }

QPushButton#hostBtn { background-color: #009938; color: #00ff41; border: none; }
QPushButton#hostBtn:hover { background-color: #00bb44; }
QPushButton#joinBtn { background-color: #000000; color: #00e038; border-color: #003800; }
QPushButton#joinBtn:hover { background-color: #001400; border-color: #006600; }

QPushButton#langBtn { color: #005a1c; border-color: #002200; }
QPushButton#langBtn:hover { color: #00aa34; border-color: #005500; }
QPushButton#langBtnActive { background: #001c00; border-color: #006600; color: #00ff41; }

QProgressBar { background-color: #000e00; }
QProgressBar::chunk { background-color: #00aa34; }
QMessageBox { background-color: #000a00; }
QMessageBox QLabel { color: #00cc44; }
""",
    },
}
