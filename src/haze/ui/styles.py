DARK_QSS = """
* { outline: none; }

QWidget {
    background-color: #000000;
    color: #e8e8e8;
    font-family: "Inter", "SF Pro Text", "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
    selection-background-color: #2a2a2a;
    selection-color: #ffffff;
    border: none;
}

QMainWindow { background-color: #000000; }

/* ── Title bar ── */
#titleBar {
    background-color: rgba(4, 4, 6, 255);
    border-bottom: 1px solid #0e0e0e;
    min-height: 42px;
    max-height: 42px;
}


#onionLabel {
    font-size: 9px;
    color: #666666;
    font-family: "JetBrains Mono", "Fira Code", monospace;
    padding: 0px 10px;
    background: rgba(8,8,10,220);
    border: 1px solid #1a1a1a;
    border-radius: 5px;
    min-height: 24px;
    max-height: 24px;
}

QPushButton#copyBtn {
    background: transparent;
    border: 1px solid #181818;
    color: #555555;
    padding: 2px 10px;
    font-size: 11px;
    border-radius: 5px;
    min-height: 24px;
}
QPushButton#copyBtn:hover { color: #cccccc; border-color: #303030; background: rgba(15,15,15,200); }

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
    color: #444444;
    border: none;
    border-radius: 5px;
    font-size: 12px;
    min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px;
}
#winBtn:hover { background: rgba(255,255,255,8); color: #bbbbbb; }
#winBtnClose:hover { background: rgba(255,40,40,15); color: #ff4040; }
#winBtn { color: #444444; }

/* ── Sidebar ── */
#sidebar {
    background-color: #000000;
    border-right: 1px solid #0c0c0c;
    min-width: 200px;
    max-width: 200px;
}
#sidebarHeader { background: transparent; }
#sidebarTitle {
    color: #686868;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}
#participantCount {
    color: #606060;
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
    color: #b0b0b0;
    font-size: 12px;
    margin: 1px 8px;
    background: transparent;
}
QListWidget::item:selected { background: rgba(255,255,255,6); color: #ffffff; }
QListWidget::item:hover    { background: rgba(255,255,255,3); color: #dddddd; }

/* ── Scroll ── */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

QScrollBar:vertical {
    background: transparent;
    width: 3px; margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,12);
    border-radius: 2px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,22); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* ── Message area ── */
#msgArea { background: transparent; }

/* ── Message bubbles — semi-transparent so glow shows through ── */
#bubbleMe {
    background-color: rgba(30, 30, 32, 215);
    border: 1px solid rgba(55, 55, 58, 140);
    border-top-color: rgba(65, 65, 68, 160);
    border-radius: 18px 18px 4px 18px;
    max-width: 540px;
}
#bubbleOther {
    background-color: rgba(14, 14, 16, 210);
    border: 1px solid rgba(35, 35, 38, 120);
    border-top-color: rgba(45, 45, 48, 140);
    border-radius: 18px 18px 18px 4px;
    max-width: 540px;
}
#nickLabel {
    font-size: 10px;
    font-weight: 700;
    color: #707070;
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
    color: #787878;
    background: transparent;
}

/* ── System messages ── */
#systemMsg {
    color: #7a7a7a;
    font-size: 11px;
    font-style: italic;
    background: transparent;
}

/* ── Input bar ── */
#inputBar {
    background-color: rgba(3, 3, 5, 240);
    border-top: 1px solid rgba(20, 20, 20, 220);
    padding: 12px 18px 16px;
}
QLineEdit#messageInput {
    background-color: rgba(12, 12, 14, 220);
    border: 1px solid rgba(30, 30, 32, 180);
    border-radius: 22px;
    padding: 12px 20px;
    color: #f0f0f0;
    font-size: 13px;
}
QLineEdit#messageInput:focus {
    border-color: rgba(60, 60, 64, 200);
    background-color: rgba(16, 16, 18, 230);
}
QLineEdit#messageInput::placeholder { color: #2c2c2c; }

QPushButton#sendBtn {
    background-color: #ffffff;
    color: #000000;
    border: none;
    border-radius: 22px;
    font-size: 17px;
    font-weight: 700;
}
QPushButton#sendBtn:hover  { background-color: #dcdcdc; }
QPushButton#sendBtn:pressed{ background-color: #b0b0b0; }

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
    color: #686868;
    letter-spacing: 0.5px;
    background: transparent;
}
#sloganSub {
    font-size: 10px;
    color: #585858;
    letter-spacing: 3px;
    background: transparent;
}

/* ── Setup dialog ── */
#logoText {
    font-size: 44px; font-weight: 800;
    color: #ffffff; letter-spacing: 14px;
}
#taglineLabel { font-size: 10px; color: #555555; letter-spacing: 3px; }
#sectionTitle { font-size: 10px; font-weight: 700; color: #888888; letter-spacing: 2px; }
#warnLabel    { font-size: 10px; color: #555555; }
#statusMsg    { font-size: 11px; color: #888888; }

QPushButton#hostBtn {
    font-size: 14px; font-weight: 600; padding: 14px 0; border-radius: 12px;
    background-color: #ffffff; color: #000000; border: none;
}
QPushButton#hostBtn:hover  { background-color: #e8e8e8; }
QPushButton#hostBtn:pressed{ background-color: #cccccc; }

QPushButton#joinBtn {
    font-size: 14px; font-weight: 600; padding: 14px 0; border-radius: 12px;
    background-color: #000000; color: #ffffff; border: 1px solid #282828;
}
QPushButton#joinBtn:hover  { background-color: #141414; border-color: #444444; }
QPushButton#joinBtn:pressed{ background-color: #080808; }

QPushButton#langBtn {
    background: transparent; border: 1px solid #1e1e1e;
    color: #444444; font-size: 11px; font-weight: 700;
    letter-spacing: 1px; padding: 3px 9px; border-radius: 6px;
}
QPushButton#langBtn:hover { color: #888888; border-color: #333333; }
QPushButton#langBtnActive {
    background: #141414; border: 1px solid #383838;
    color: #ffffff; font-size: 11px; font-weight: 700;
    letter-spacing: 1px; padding: 3px 9px; border-radius: 6px;
}

QLineEdit {
    background-color: #0d0d0d; border: 1px solid #1e1e1e;
    border-radius: 10px; padding: 10px 14px; color: #ffffff; font-size: 13px;
}
QLineEdit:focus { border-color: #404040; background-color: #111111; }
QLineEdit::placeholder { color: #3a3a3a; }

QProgressBar {
    background-color: #0d0d0d; border: none; border-radius: 2px; max-height: 2px;
}
QProgressBar::chunk { background-color: #ffffff; border-radius: 2px; }

/* ── Splitter ── */
QSplitter::handle:horizontal { background-color: #0a0a0a; width: 1px; }

/* ── Menu ── */
QMenu {
    background-color: rgba(12,12,14,250); border: 1px solid #1a1a1a;
    border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 9px 20px; border-radius: 6px; color: #d8d8d8; font-size: 13px; }
QMenu::item:selected { background-color: rgba(255,255,255,8); color: #ffffff; }
QMenu::separator { height: 1px; background: #141414; margin: 4px 8px; }

QToolTip {
    background-color: rgba(16,16,18,250); color: #c0c0c0;
    border: 1px solid #1e1e1e; border-radius: 6px;
    padding: 5px 10px; font-size: 11px;
}

QMessageBox { background-color: #0d0d0d; }
QMessageBox QLabel { color: #dddddd; font-size: 13px; }
QMessageBox QPushButton { min-width: 80px; }

/* ── Protocol badge as button ── */
QPushButton#protocolBadgeActive {
    font-size: 9px;
    font-weight: 700;
    color: #34c759;
    letter-spacing: 1.5px;
    padding: 2px 7px;
    border: 1px solid #0a2e14;
    border-radius: 6px;
    background-color: #020905;
}
QPushButton#protocolBadgeActive:hover {
    background-color: #041510;
    border-color: #1a5e2c;
}
QPushButton#protocolBadge {
    font-size: 9px;
    font-weight: 700;
    color: #444444;
    letter-spacing: 1.5px;
    padding: 2px 7px;
    border: 1px solid #161616;
    border-radius: 6px;
    background-color: #060606;
}
QPushButton#protocolBadge:hover {
    color: #666666;
    border-color: #282828;
}

/* ── Protocol info popup ── */
#protocolPanel {
    background-color: rgba(7, 7, 9, 248);
    border: 1px solid rgba(48, 48, 54, 255);
    border-top-color: rgba(65, 65, 72, 255);
    border-radius: 20px;
}
#popupTitle {
    font-size: 11px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 3px;
    background: transparent;
}
#popupEncBadge {
    font-size: 9px;
    font-weight: 700;
    color: #34c759;
    letter-spacing: 1.5px;
    padding: 2px 8px;
    border: 1px solid #0a2e14;
    border-radius: 6px;
    background-color: #020905;
}
#popupSectionLabel {
    font-size: 9px;
    font-weight: 700;
    color: #686868;
    letter-spacing: 2.5px;
    background: transparent;
}
#popupKey {
    font-size: 12px;
    color: #848484;
    background: transparent;
}
#popupValue {
    font-size: 12px;
    color: #c8c8c8;
    font-weight: 600;
    background: transparent;
}
#popupValueGreen {
    font-size: 12px;
    color: #34c759;
    font-weight: 600;
    background: transparent;
}
QPushButton#popupCloseBtn {
    background: rgba(22, 22, 26, 200);
    color: #444444;
    border: 1px solid #242428;
    border-radius: 14px;
    font-size: 13px;
    min-width: 28px; max-width: 28px;
    min-height: 28px; max-height: 28px;
}
QPushButton#popupCloseBtn:hover {
    color: #aaaaaa;
    border-color: #404040;
    background: rgba(36, 36, 40, 220);
}
"""
