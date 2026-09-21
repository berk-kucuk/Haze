import json
import os
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
    # Privacy
    "blur_messages": False,
    # Chat
    "send_typing_indicators": True,
    "show_timestamps": True,
    "enter_to_send": True,
    # Tor connection method — "direct", "vanilla", "obfs4" or "snowflake"
    # (see haze.tor.bridges). Read before Tor starts, so it lives here rather
    # than in per-session state.
    "tor_bridge_mode": "direct",
    "tor_bridges_custom": "",       # user-supplied bridge lines, one per line
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
    """Persist settings, readable only by this user.

    This file holds vault_lock_hash and vault_decoy_hash. Written with the
    default umask it lands at 0644, and both consequences matter:

      * The lock hash becomes available to every local account, which turns a
        rate-limited unlock prompt into an offline guessing problem. scrypt at
        N=2^15 keeps that expensive, but it should not be on offer at all.

      * Worse, a non-empty vault_decoy_hash ANNOUNCES that a decoy vault
        exists. A decoy is only worth having while nobody knows to ask for the
        other password, so a world-readable copy defeats the entire feature
        rather than merely weakening it.

    The directory is tightened too: 0644 on the file is no help if the
    directory itself lets anyone list and read what is in it.
    """
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_CONFIG_DIR, 0o700)
    except OSError:
        pass
    # Create with 0600 from the start rather than chmod-ing afterwards: between
    # the two there is a window where the hashes are on disk and readable.
    fd = os.open(_SETTINGS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(settings, f, indent=2)
    # An existing file keeps its old mode through O_CREAT, so fix it explicitly
    # for anyone upgrading from a version that wrote it world-readable.
    try:
        os.chmod(_SETTINGS_FILE, 0o600)
    except OSError:
        pass
