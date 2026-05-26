import json
from pathlib import Path

_CONFIG_DIR = Path.home() / ".config" / "haze"
_SETTINGS_FILE = _CONFIG_DIR / "settings.json"

_DEFAULTS: dict = {
    "notifications_enabled": True,
    "notifications_show_content": True,
    "theme": "haze",
    "disappearing_messages": 0,    # 0=off, 30, 300, 3600 seconds
    "vault_lock_hash": "",          # empty = no lock
    "vault_decoy_hash": "",         # empty = no decoy
}


def load() -> dict:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE) as f:
                return {**_DEFAULTS, **json.load(f)}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(settings: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
