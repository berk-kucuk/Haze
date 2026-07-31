"""Minimal i18n — add more languages by extending _STRINGS."""

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Setup dialog
        "start_chat":       "Start Chat",
        "join":             "Join",
        "username":         "USERNAME",
        "onion_address":    "SESSION ADDRESS",
        "connect":          "Connect",
        "tor_warning":      "Tor must be installed  ·  All communication is encrypted and anonymous",
        "starting_tor":     "Starting Tor…",
        "creating_hs":      "Creating hidden service (30-60 s)…",
        "ready":            "Ready.",
        "connection_error": "Connection Error",
        "select_mode":      "Select 'Start Chat' or 'Join' first.",
        "username_empty":   "Username cannot be empty.",
        "username_chars":   "Username: letters, numbers, _ and - only.",
        "onion_required":   "A session address is required.",
        "placeholder_nick": "ghost_42  (max 20 chars)",
        "placeholder_onion":"abc123…xyz",
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
        "chat_started":     "Chat started — share your session address to invite others",
        "connecting_to":    "Connecting to {}",
        "connected":        "Connected",
        "disconnected":     "Connection lost",
        "connection_lost":  "Connection lost",
        "reconnect":        "Reconnect",
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
        # Notifications
        "new_message_notification": "New message received",
        # Settings
        "settings":                 "SETTINGS",
        "notifications":            "NOTIFICATIONS",
        "enable_notifications":     "Enable notifications",
        "show_message_content":     "Show message content",
        "close":                    "Close",
        "save":                     "Save",
        # Vault
        "vault":                    "SECRET VAULT",
        "vault_save_session":       "Save Current Session",
        "vault_saved_sessions":     "SAVED SESSIONS",
        "vault_empty":              "No saved sessions",
        "vault_no_messages":        "No chat messages to save.",
        "vault_session_name":       "Session name:",
        "vault_password_prompt":    "Vault password:",
        "vault_password_confirm":   "Confirm password:",
        "vault_password_mismatch":  "Passwords do not match.",
        "vault_wrong_password":     "Wrong password.",
        "vault_saved":              "Session saved to vault.",
        "vault_view":               "View",
        "vault_delete_confirm":     "Delete this session?",
        # Multi-session
        "new_session":              "New Session",
        "close_session":            "Close Session",
        "session_nick":             "Nickname for this session",
        # Theme
        "theme":                    "THEME",
        # File transfer
        "attach_file":              "Attach file",
        "file_sent":                "Sent",
        "file_receiving":           "Receiving…",
        "file_download":            "Download",
        "file_save_as":             "Save file as…",
        "file_too_large":           "File is too large (max 100 MB).",
        "file_send_error":          "Failed to send file.",
        # Kick
        "kick_user":                "Kick from session",
        "you_were_kicked":          "You have been removed from this session.",
        # Typing
        "is_typing":                "{} is typing…",
        # Delete / Edit
        "msg_deleted":              "Message deleted",
        "msg_edited":               "(edited)",
        "edit_message":             "Edit",
        "delete_message":           "Delete",
        "message_deleted":          "This message was deleted",
        "edit_dialog_title":        "Edit Message",
        "edit_dialog_label":        "New content:",
        # Disappearing messages
        "disappearing_messages":    "DISAPPEARING MESSAGES",
        "disappear_off":            "Off",
        "disappear_30s":            "30 sec",
        "disappear_5m":             "5 min",
        "disappear_1h":             "1 hour",
        # Voice note
        "voice_note":               "Hold to record",
        "voice_note_sending":       "Sending voice note…",
        # Search
        "search_placeholder":       "Search messages…",
        "search_no_results":        "No results",
        # QR code
        "qr_title":                 "SHARE SESSION ADDRESS",
        "qr_copy":                  "Copy Address",
        "open_in_tor_browser":      "Open in Tor Browser",
        "open_in_tor_browser_hint": "Open this session's web chat directly in Tor Browser",
        "tor_browser_missing":      "Tor Browser wasn't found. The address was copied to your clipboard — paste it into a Tor Browser address bar:\n\n{}",
        # Vault lock / duress
        "vault_lock":               "VAULT LOCK",
        "vault_lock_set":           "Set lock password",
        "vault_lock_remove":        "Remove lock",
        "vault_decoy":              "DURESS PASSWORD",
        "vault_decoy_hint":         "Enter this password under coercion — shows empty vault",
        "vault_decoy_set":          "Set decoy password",
        "vault_decoy_remove":       "Remove decoy",
        "vault_locked":             "Vault is locked. Enter password:",
        "vault_unlock":             "Unlock",
        "vault_lock_wrong":         "Wrong vault password.",
        "vault_decoy_active":       "Decoy mode — vault appears empty.",
        "vault_password_new":       "New password:",
        "vault_password_set_ok":    "Password set.",
        # Latency
        "latency_good":             "Connection: good",
        "latency_medium":           "Connection: moderate",
        "latency_poor":             "Connection: poor",
        "latency_unknown":          "Connection: measuring…",
        # Session password
        "session_password":         "SESSION PASSWORD",
        "session_password_host":    "Set a password (optional)",
        "session_password_join":    "Session password (if required)",
        "auth_failed_title":        "Authentication Failed",
        "auth_failed_msg":          "Wrong session password. The host requires a correct password to join.",
        "session_locked":           "Session is password-protected",
        # Connect page
        "host_mode":                "Host",
        "disconnect":               "Disconnect",
        "disconnect_confirm":       "Leave this session?",
        # Reply
        "reply_message":            "Reply",
        "copy_message":             "Copy",
        "reply_to":                 "Replying to",
        "reply_cancel":             "Cancel Reply",
        # Privacy settings
        "privacy":                  "PRIVACY",
        "blur_messages":            "Blur messages (click to reveal)",
        # Chat settings
        "chat":                     "CHAT",
        "send_typing_indicators":   "Send typing indicator",
        "show_timestamps":          "Show timestamps",
        "enter_to_send":            "Enter to send",
        # Tor connection method / bridges
        "error":                    "Error",
        "tor_connection":           "TOR CONNECTION",
        "tor_conn_open":            "Tor blocked?  ·  Connection settings",
        "tor_conn_direct":          "Direct",
        "tor_conn_vanilla":         "Bridge",
        "tor_conn_obfs4":           "obfs4",
        "tor_conn_snowflake":       "Snowflake",
        "tor_conn_desc_direct":     (
            "Connect straight to the Tor network. Fastest, but blocked in "
            "countries that filter Tor."
        ),
        "tor_conn_desc_vanilla":    (
            "Connect through an unlisted relay. Gets past blocked relay "
            "addresses, but the traffic still looks like Tor to a censor "
            "inspecting it. Your own bridge lines are required."
        ),
        "tor_conn_desc_obfs4":      (
            "Bridges that disguise the traffic so it looks like nothing in "
            "particular. The best choice where Tor is blocked."
        ),
        "tor_conn_desc_snowflake":  (
            "Routes through volunteers' browsers over WebRTC, hidden behind a "
            "CDN. Works where obfs4 is already blocked; often slower."
        ),
        "tor_conn_custom":          "YOUR OWN BRIDGE LINES",
        "tor_conn_custom_optional": "optional — replaces the built-in bridges",
        "tor_conn_custom_required": "required for this method",
        "tor_conn_custom_hint":     (
            "One per line. Get bridges from bridges.torproject.org, from "
            "@GetBridgesBot on Telegram, or by mailing bridges@torproject.org."
        ),
        "tor_conn_builtin":         (
            "Using {} built-in bridges. Censors know these too — paste fresh "
            "ones above if they stop working."
        ),
        "tor_conn_binary_ok":       "✓  {} found",
        "tor_conn_binary_missing":  "✗  {} is not installed  ·  {}",
        "tor_conn_no_lines":        "Add at least one bridge line.",
        "tor_conn_restart_note":    "Takes effect the next time Haze starts.",
        "tor_conn_slow_note":       "Connecting through a bridge can take a few minutes.",
        "tor_bootstrap_hint":       (
            "If Tor is blocked on your network, try a bridge under "
            "'Connection settings'."
        ),
    },

    "tr": {
        # Setup dialog
        "start_chat":       "Sohbet Başlat",
        "join":             "Katıl",
        "username":         "KULLANICI ADI",
        "onion_address":    "SESSION ADRESİ",
        "connect":          "Bağlan",
        "tor_warning":      "Tor kurulu olmalıdır  ·  Tüm iletişim şifreli ve isimsizdir",
        "starting_tor":     "Tor başlatılıyor…",
        "creating_hs":      "Hidden service oluşturuluyor (30-60 sn)…",
        "ready":            "Hazır.",
        "connection_error": "Bağlantı Hatası",
        "select_mode":      "Önce 'Sohbet Başlat' veya 'Katıl' seçin.",
        "username_empty":   "Kullanıcı adı boş olamaz.",
        "username_chars":   "Kullanıcı adı: harf, rakam, _ ve - içerebilir.",
        "onion_required":   "Session adresi girilmeli.",
        "placeholder_nick": "ghost_42  (max 20 karakter)",
        "placeholder_onion":"abc123…xyz",
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
        "chat_started":     "Sohbet başlatıldı — adresini paylaşarak davet et",
        "connecting_to":    "Bağlanılıyor: {}",
        "connected":        "Bağlantı kuruldu",
        "disconnected":     "Bağlantı kesildi",
        "connection_lost":  "Bağlantı kesildi",
        "reconnect":        "Yeniden bağlan",
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
        # Bildirimler
        "new_message_notification": "Yeni mesaj alındı",
        # Ayarlar
        "settings":                 "AYARLAR",
        "notifications":            "BİLDİRİMLER",
        "enable_notifications":     "Bildirimleri etkinleştir",
        "show_message_content":     "Mesaj içeriğini göster",
        "close":                    "Kapat",
        "save":                     "Kaydet",
        # Kasa
        "vault":                    "GİZLİ KASA",
        "vault_save_session":       "Mevcut Oturumu Kaydet",
        "vault_saved_sessions":     "KAYITLI OTURUMLAR",
        "vault_empty":              "Kayıtlı oturum yok",
        "vault_no_messages":        "Kaydedilecek mesaj bulunamadı.",
        "vault_session_name":       "Oturum adı:",
        "vault_password_prompt":    "Kasa şifresi:",
        "vault_password_confirm":   "Şifreyi onayla:",
        "vault_password_mismatch":  "Şifreler eşleşmiyor.",
        "vault_wrong_password":     "Yanlış şifre.",
        "vault_saved":              "Oturum kasaya kaydedildi.",
        "vault_view":               "Görüntüle",
        "vault_delete_confirm":     "Bu oturum silinsin mi?",
        # Çoklu oturum
        "new_session":              "Yeni Oturum",
        "close_session":            "Oturumu Kapat",
        "session_nick":             "Bu oturum için takma ad",
        # Tema
        "theme":                    "TEMA",
        # Dosya transferi
        "attach_file":              "Dosya ekle",
        "file_sent":                "Gönderildi",
        "file_receiving":           "Alınıyor…",
        "file_download":            "İndir",
        "file_save_as":             "Dosyayı farklı kaydet…",
        "file_too_large":           "Dosya çok büyük (max 100 MB).",
        "file_send_error":          "Dosya gönderilemedi.",
        # Kullanıcı atma
        "kick_user":                "Sohbetten çıkar",
        "you_were_kicked":          "Bu oturumdan çıkarıldınız.",
        # Yazıyor
        "is_typing":                "{} yazıyor…",
        # Sil / Düzenle
        "msg_deleted":              "Mesaj silindi",
        "msg_edited":               "(düzenlendi)",
        "edit_message":             "Düzenle",
        "delete_message":           "Sil",
        "message_deleted":          "Bu mesaj silindi",
        "edit_dialog_title":        "Mesajı Düzenle",
        "edit_dialog_label":        "Yeni içerik:",
        # Kaybolan mesajlar
        "disappearing_messages":    "KAYBOLAN MESAJLAR",
        "disappear_off":            "Kapalı",
        "disappear_30s":            "30 sn",
        "disappear_5m":             "5 dk",
        "disappear_1h":             "1 saat",
        # Sesli not
        "voice_note":               "Kayıt için basılı tut",
        "voice_note_sending":       "Sesli not gönderiliyor…",
        # Arama
        "search_placeholder":       "Mesajlarda ara…",
        "search_no_results":        "Sonuç bulunamadı",
        # QR kod
        "qr_title":                 "SESSION ADRESİ PAYLAŞ",
        "qr_copy":                  "Adresi Kopyala",
        "open_in_tor_browser":      "Tor Browser'da Aç",
        "open_in_tor_browser_hint": "Bu oturumun web sohbetini doğrudan Tor Browser'da aç",
        "tor_browser_missing":      "Tor Browser bulunamadı. Adres panoya kopyalandı — Tor Browser adres çubuğuna yapıştırın:\n\n{}",
        # Kasa kilidi / duress
        "vault_lock":               "KASA KİLİDİ",
        "vault_lock_set":           "Kilit şifresi belirle",
        "vault_lock_remove":        "Kilidi kaldır",
        "vault_decoy":              "BASKIYA KARŞI ŞİFRE",
        "vault_decoy_hint":         "Baskı altında bu şifreyi gir — kasa boş görünür",
        "vault_decoy_set":          "Sahte şifre belirle",
        "vault_decoy_remove":       "Sahte şifreyi kaldır",
        "vault_locked":             "Kasa kilitli. Şifre girin:",
        "vault_unlock":             "Kilidi Aç",
        "vault_lock_wrong":         "Yanlış kasa şifresi.",
        "vault_decoy_active":       "Baskı modu — kasa boş görünüyor.",
        "vault_password_new":       "Yeni şifre:",
        "vault_password_set_ok":    "Şifre belirlendi.",
        # Gecikme
        "latency_good":             "Bağlantı: iyi",
        "latency_medium":           "Bağlantı: orta",
        "latency_poor":             "Bağlantı: zayıf",
        "latency_unknown":          "Bağlantı: ölçülüyor…",
        # Oturum şifresi
        "session_password":         "OTURUM ŞİFRESİ",
        "session_password_host":    "Şifre belirle (isteğe bağlı)",
        "session_password_join":    "Oturum şifresi (gerekiyorsa)",
        "auth_failed_title":        "Kimlik Doğrulama Başarısız",
        "auth_failed_msg":          "Yanlış oturum şifresi. Katılmak için doğru şifreyi girmeniz gerekiyor.",
        "session_locked":           "Oturum şifre korumalı",
        # Bağlan sayfası
        "host_mode":                "Host",
        "disconnect":               "Bağlantıyı Kes",
        "disconnect_confirm":       "Bu oturumdan ayrılmak istediğinize emin misiniz?",
        # Yanıt
        "reply_message":            "Yanıtla",
        "copy_message":             "Kopyala",
        "reply_to":                 "Yanıtlanıyor",
        "reply_cancel":             "Yanıtı İptal Et",
        # Gizlilik ayarları
        "privacy":                  "GİZLİLİK",
        "blur_messages":            "Mesajları bulanık göster (tıkla açılır)",
        # Sohbet ayarları
        "chat":                     "SOHBET",
        "send_typing_indicators":   "Yazıyor göster",
        "show_timestamps":          "Zaman damgasını göster",
        "enter_to_send":            "Enter ile gönder",
        # Tor bağlantı yöntemi / köprüler
        "error":                    "Hata",
        "tor_connection":           "TOR BAĞLANTISI",
        "tor_conn_open":            "Tor engelli mi?  ·  Bağlantı ayarları",
        "tor_conn_direct":          "Doğrudan",
        "tor_conn_vanilla":         "Köprü",
        "tor_conn_obfs4":           "obfs4",
        "tor_conn_snowflake":       "Snowflake",
        "tor_conn_desc_direct":     (
            "Tor ağına doğrudan bağlan. En hızlısı, ama Tor'u filtreleyen "
            "ülkelerde engellenir."
        ),
        "tor_conn_desc_vanilla":    (
            "Listelenmemiş bir aktarıcı üzerinden bağlan. Engellenen aktarıcı "
            "adreslerini aşar, ancak trafiği inceleyen bir sansürcü için hâlâ "
            "Tor gibi görünür. Kendi köprü satırlarını girmen gerekir."
        ),
        "tor_conn_desc_obfs4":      (
            "Trafiği hiçbir şeye benzemeyecek şekilde gizleyen köprüler. "
            "Tor'un engelli olduğu yerlerde en iyi seçenek."
        ),
        "tor_conn_desc_snowflake":  (
            "WebRTC ile gönüllülerin tarayıcıları üzerinden, bir CDN'in "
            "arkasına saklanarak bağlanır. obfs4 de engelliyse işe yarar; "
            "genelde daha yavaştır."
        ),
        "tor_conn_custom":          "KENDİ KÖPRÜ SATIRLARIN",
        "tor_conn_custom_optional": "isteğe bağlı — gömülü köprülerin yerine geçer",
        "tor_conn_custom_required": "bu yöntem için zorunlu",
        "tor_conn_custom_hint":     (
            "Her satıra bir tane. Köprüleri bridges.torproject.org'dan, "
            "Telegram'da @GetBridgesBot'tan veya bridges@torproject.org'a "
            "e-posta atarak alabilirsin."
        ),
        "tor_conn_builtin":         (
            "{} gömülü köprü kullanılıyor. Sansürcüler bunları da biliyor — "
            "çalışmazlarsa yukarıya yenilerini yapıştır."
        ),
        "tor_conn_binary_ok":       "✓  {} bulundu",
        "tor_conn_binary_missing":  "✗  {} kurulu değil  ·  {}",
        "tor_conn_no_lines":        "En az bir köprü satırı gir.",
        "tor_conn_restart_note":    "Haze'in bir sonraki açılışında geçerli olur.",
        "tor_conn_slow_note":       "Köprü üzerinden bağlanmak birkaç dakika sürebilir.",
        "tor_bootstrap_hint":       (
            "Ağında Tor engelliyse 'Bağlantı ayarları' altından bir köprü "
            "yöntemi dene."
        ),
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
