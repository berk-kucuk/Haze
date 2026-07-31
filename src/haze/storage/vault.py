"""
Encrypted vault for saved sessions.

KEY DERIVATION: scrypt (memory-hard), replacing PBKDF2. PBKDF2 needs almost no
memory, so an attacker who copies the vault off a seized device can try
passwords on GPUs at enormous rates. scrypt at N=2^15 forces 32 MiB per guess
for the same ~100 ms the old PBKDF2 cost here, which is the parameter that
actually slows cracking hardware down.

Vaults written by older versions are still readable: files carry a magic
prefix, hashes carry a scheme prefix, and anything without one is treated as
legacy PBKDF2 and re-encrypted with scrypt the next time it is written.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_VAULT_DIR = Path.home() / ".config" / "haze" / "vault"
_SALT_FILE = _VAULT_DIR / ".salt"

_LOCK_SALT  = b"haze_vault_lock_v1"
_DECOY_SALT = b"haze_vault_decoy_v1"

# Marks a vault file whose key came from scrypt. Legacy files begin with a raw
# 12-byte nonce, so the prefix is what tells the two apart.
_MAGIC_V2 = b"HZV2"
# Marks a lock/decoy hash produced by scrypt; a bare hex string is legacy.
_SCRYPT_PREFIX = "scrypt$"

# 32 MiB, ~100 ms per guess. Kept identical on Android (VaultStore.kt) so both
# platforms resist cracking to the same degree.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1


def _get_or_create_salt() -> bytes:
    _VAULT_DIR.mkdir(parents=True, exist_ok=True)
    if _SALT_FILE.exists():
        return _SALT_FILE.read_bytes()
    salt = os.urandom(32)
    _SALT_FILE.write_bytes(salt)
    return salt


def _derive_key(password: str, salt: bytes) -> bytes:
    """Current KDF: memory-hard scrypt."""
    kdf = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(password.encode())


def _derive_key_legacy(password: str, salt: bytes) -> bytes:
    """KDF used by vaults written before the scrypt migration. Read-only."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return kdf.derive(password.encode())


def _scrypt_hex(password: str, salt: bytes) -> str:
    # cryptography's Scrypt rather than hashlib.scrypt: the latter goes through
    # OpenSSL, whose default 32 MB memory ceiling these parameters exceed.
    return _SCRYPT_PREFIX + _derive_key(password, salt).hex()


def _pbkdf2_hex(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return dk.hex()


# ------------------------------------------------------------------
# Lock / decoy helpers (used by settings UI)
# ------------------------------------------------------------------

def make_lock_hash(password: str) -> str:
    return _scrypt_hex(password, _LOCK_SALT)

def make_decoy_hash(password: str) -> str:
    return _scrypt_hex(password, _DECOY_SALT)


def _matches(password: str, stored_hash: str, salt: bytes) -> bool:
    """Compare against either hash scheme, in constant time.

    Constant time because a plain `==` on hex strings leaks how many leading
    characters matched, which is enough to reconstruct the stored digest one
    character at a time.
    """
    if stored_hash.startswith(_SCRYPT_PREFIX):
        return hmac.compare_digest(_scrypt_hex(password, salt), stored_hash)
    return hmac.compare_digest(_pbkdf2_hex(password, salt), stored_hash)


def check_lock(password: str, stored_hash: str) -> bool:
    """True if no lock is set OR password matches lock hash."""
    if not stored_hash:
        return True
    return _matches(password, stored_hash, _LOCK_SALT)

def check_decoy(password: str, stored_hash: str) -> bool:
    """True if password matches the decoy hash."""
    if not stored_hash:
        return False
    return _matches(password, stored_hash, _DECOY_SALT)


def is_legacy_hash(stored_hash: str) -> bool:
    """True for a lock/decoy hash still using the old PBKDF2 scheme.

    Callers re-save the upgraded hash after a successful unlock, when the
    password is in hand — see MainWindow's vault unlock path.
    """
    return bool(stored_hash) and not stored_hash.startswith(_SCRYPT_PREFIX)


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
    (_VAULT_DIR / filename).write_bytes(_MAGIC_V2 + nonce + ct)


def load_session(password: str, path: str) -> dict:
    """Raises InvalidTag if the password is wrong.

    Reads both layouts: scrypt files carry the magic prefix, older PBKDF2 files
    start straight into the nonce.
    """
    salt = _get_or_create_salt()
    raw = Path(path).read_bytes()

    if raw.startswith(_MAGIC_V2):
        body = raw[len(_MAGIC_V2):]
        try:
            key = _derive_key(password, salt)
            return json.loads(
                ChaCha20Poly1305(key).decrypt(body[:12], body[12:], None).decode()
            )
        except InvalidTag:
            # A legacy file whose random nonce happened to start with the magic
            # bytes lands here (1 in 2^32). Fall through and try it as legacy.
            pass

    key = _derive_key_legacy(password, salt)
    plaintext = ChaCha20Poly1305(key).decrypt(raw[:12], raw[12:], None)
    return json.loads(plaintext.decode())


def delete_session(path: str) -> None:
    Path(path).unlink(missing_ok=True)
