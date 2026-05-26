import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_VAULT_DIR = Path.home() / ".config" / "haze" / "vault"
_SALT_FILE = _VAULT_DIR / ".salt"

_LOCK_SALT  = b"haze_vault_lock_v1"
_DECOY_SALT = b"haze_vault_decoy_v1"


def _get_or_create_salt() -> bytes:
    _VAULT_DIR.mkdir(parents=True, exist_ok=True)
    if _SALT_FILE.exists():
        return _SALT_FILE.read_bytes()
    salt = os.urandom(32)
    _SALT_FILE.write_bytes(salt)
    return salt


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return kdf.derive(password.encode())


def _pbkdf2_hex(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return dk.hex()


# ------------------------------------------------------------------
# Lock / decoy helpers (used by settings UI)
# ------------------------------------------------------------------

def make_lock_hash(password: str) -> str:
    return _pbkdf2_hex(password, _LOCK_SALT)

def make_decoy_hash(password: str) -> str:
    return _pbkdf2_hex(password, _DECOY_SALT)

def check_lock(password: str, stored_hash: str) -> bool:
    """True if no lock is set OR password matches lock hash."""
    if not stored_hash:
        return True
    return make_lock_hash(password) == stored_hash

def check_decoy(password: str, stored_hash: str) -> bool:
    """True if password matches the decoy hash."""
    if not stored_hash:
        return False
    return make_decoy_hash(password) == stored_hash


# ------------------------------------------------------------------
# Session list
# ------------------------------------------------------------------

def salt_exists() -> bool:
    return _SALT_FILE.exists()


def list_sessions() -> list[dict]:
    if not _VAULT_DIR.exists():
        return []
    return [
        {"filename": f.name, "path": str(f)}
        for f in sorted(_VAULT_DIR.glob("*.hzv"), reverse=True)
    ]


# ------------------------------------------------------------------
# Save / load / delete
# ------------------------------------------------------------------

def save_session(password: str, session_name: str, messages: list, participants: list) -> None:
    salt = _get_or_create_salt()
    key = _derive_key(password, salt)

    data = {
        "session_name": session_name,
        "participants": participants,
        "timestamp": datetime.now().isoformat(),
        "messages": messages,
    }
    plaintext = json.dumps(data).encode()
    nonce = os.urandom(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext, None)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in session_name if c.isalnum() or c in "_- ")[:20].strip()
    filename = f"{ts}_{safe_name or 'session'}.hzv"
    (_VAULT_DIR / filename).write_bytes(nonce + ct)


def load_session(password: str, path: str) -> dict:
    """Raises InvalidTag if the password is wrong."""
    salt = _get_or_create_salt()
    key = _derive_key(password, salt)
    raw = Path(path).read_bytes()
    nonce, ct = raw[:12], raw[12:]
    plaintext = ChaCha20Poly1305(key).decrypt(nonce, ct, None)
    return json.loads(plaintext.decode())


def delete_session(path: str) -> None:
    Path(path).unlink(missing_ok=True)
