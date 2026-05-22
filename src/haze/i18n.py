"""Minimal i18n — add more languages by extending _STRINGS."""

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Setup dialog
        "start_chat":       "Start Chat",
        "join":             "Join",
        "username":         "USERNAME",
        "onion_address":    ".ONION ADDRESS",
        "connect":          "Connect",
        "tor_warning":      "Tor must be installed  ·  All communication is encrypted and anonymous",
        "starting_tor":     "Starting Tor…",
        "creating_hs":      "Creating hidden service (30-60 s)…",
        "ready":            "Ready.",
        "connection_error": "Connection Error",
        "select_mode":      "Select 'Start Chat' or 'Join' first.",
        "username_empty":   "Username cannot be empty.",
        "username_chars":   "Username: letters, numbers, _ and - only.",
        "onion_required":   "A .onion address is required.",
        "placeholder_nick": "ghost_42  (max 20 chars)",
        "placeholder_onion":"abc123…xyz.onion",
        "tagline":          "ANONYMOUS  ·  ENCRYPTED  ·  NO TRACE",
        "language":         "LANGUAGE",
        # Main window
        "online":           "ONLINE",
        "type_message":     "Type a message…",
        "panic":            "PANIC",
        "copy":             "Copy",
        "protocol_active":  "● HAZE PROTOCOL",
        "protocol_lost":    "● DISCONNECTED",
        "slogan":           "Your words dissolve into the haze.",
        "slogan_sub":       "HAZE PROTOCOL  ·  END-TO-END ENCRYPTED  ·  NO LOGS",
        "chat_started":     "Chat started — share your .onion address to invite others",
        "connecting_to":    "Connecting to {}",
        "connected":        "Connected",
        "disconnected":     "Connection lost",
        "joined":           "{} joined",
        "left":             "{} left",
        "me_suffix":        " (you)",
        # Panic
        "panic_title":      "PANIC",
        "panic_confirm":    (
            "When you press the panic button:\n\n"
            "  • All users are alerted\n"
            "  • Session is immediately terminated\n"
            "  • All traces are erased\n\n"
            "Do you want to continue?"
        ),
        "panic_received_title": "⚠ PANIC",
        "panic_received":   "{} pressed the panic button!\n\nLeave immediately for your safety.",
        "panic_banner":     "PANIC — {}\nPanic button pressed. Disconnect now.",
        "panic_triggered":    "⚠  PANIC initiated — wiping session",
        "panic_triggered_by": "⚠  {} pressed PANIC — session is being wiped",
        # Tray
        "tray_tooltip":     "Haze — active",
        "tray_open":        "Open Haze",
        "tray_panic":       "⚠ PANIC",
        "tray_quit":        "Quit Session",
        "tray_hidden":      "Haze is running in the system tray.",
    },
    "tr": {
        # Setup dialog
        "start_chat":       "Sohbet Başlat",
        "join":             "Katıl",
        "username":         "KULLANICI ADI",
        "onion_address":    ".ONION ADRESİ",
        "connect":          "Bağlan",
        "tor_warning":      "Tor kurulu olmalıdır  ·  Tüm iletişim şifreli ve isimsizdir",
        "starting_tor":     "Tor başlatılıyor…",
        "creating_hs":      "Hidden service oluşturuluyor (30-60 sn)…",
        "ready":            "Hazır.",
        "connection_error": "Bağlantı Hatası",
        "select_mode":      "Önce 'Sohbet Başlat' veya 'Katıl' seçin.",
        "username_empty":   "Kullanıcı adı boş olamaz.",
        "username_chars":   "Kullanıcı adı: harf, rakam, _ ve - içerebilir.",
        "onion_required":   ".onion adresi girilmeli.",
        "placeholder_nick": "ghost_42  (max 20 karakter)",
        "placeholder_onion":"abc123…xyz.onion",
        "tagline":          "ANONİM  ·  ŞİFRELİ  ·  İZSİZ",
        "language":         "DİL",
        # Main window
        "online":           "ONLINE",
        "type_message":     "Mesaj yaz…",
        "panic":            "PANİK",
        "copy":             "Kopyala",
        "protocol_active":  "● HAZE PROTOCOL",
        "protocol_lost":    "● BAĞLANTI KESİLDİ",
        "slogan":           "Kelimeleriniz sisin içinde eriyip gider.",
        "slogan_sub":       "HAZE PROTOCOL  ·  UÇ NOKTADAN UCA ŞİFRELİ  ·  KAYIT YOK",
        "chat_started":     "Sohbet başlatıldı — .onion adresini paylaşarak davet et",
        "connecting_to":    "Bağlanılıyor: {}",
        "connected":        "Bağlantı kuruldu",
        "disconnected":     "Bağlantı kesildi",
        "joined":           "{} katıldı",
        "left":             "{} ayrıldı",
        "me_suffix":        " (sen)",
        # Panic
        "panic_title":      "PANİK",
        "panic_confirm":    (
            "Panik butonuna bastığında:\n\n"
            "  • Tüm kullanıcılar uyarılır\n"
            "  • Oturum anında sonlandırılır\n"
            "  • Tüm izler silinir\n\n"
            "Devam etmek istiyor musun?"
        ),
        "panic_received_title": "⚠ PANİK",
        "panic_received":   "{} panik butonuna bastı!\n\nGüvenliğin için hemen çık.",
        "panic_banner":     "PANİK — {}\nPanik butonuna basıldı. Hemen bağlantını kes.",
        "panic_triggered":    "⚠  PANİK başlatıldı — oturum siliniyor",
        "panic_triggered_by": "⚠  {} PANİK butonuna bastı — oturum siliniyor",
        # Tray
        "tray_tooltip":     "Haze — aktif",
        "tray_open":        "Haze'i Aç",
        "tray_panic":       "⚠ PANİK",
        "tray_quit":        "Oturumu Kapat ve Çık",
        "tray_hidden":      "Sistem tepsisinde çalışmaya devam ediyor.",
    },
}

LANGUAGES = list(_STRINGS.keys())   # ["en", "tr"]
_current = "en"


def set_lang(lang: str) -> None:
    global _current
    if lang in _STRINGS:
        _current = lang


def get_lang() -> str:
    return _current


def t(key: str) -> str:
    return _STRINGS.get(_current, _STRINGS["en"]).get(key, key)
