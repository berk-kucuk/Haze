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

# Fixed salts of the older schemes. Being the same on every installation,
# they let one precomputed table attack every Haze user's lock at once (audit
# H8); new hashes carry a random salt of their own and these are only read.
_LOCK_SALT  = b"haze_vault_lock_v1"
_DECOY_SALT = b"haze_vault_decoy_v1"

# Marks a vault file whose key came from scrypt. Legacy files begin with a raw
# 12-byte nonce, so the prefix is what tells the two apart.
_MAGIC_V2 = b"HZV2"
# Lock/decoy hash formats, newest first:
#   "scrypt2$<salt hex>$<hash hex>"  scrypt, random per-hash salt (current)
#   "scrypt$<hash hex>"              scrypt, fixed salt (legacy, read-only)
#   "<hash hex>"                     PBKDF2, fixed salt (legacy, read-only)
_SALTED_PREFIX = "scrypt2$"
_SCRYPT_PREFIX = "scrypt$"

# 32 MiB, ~100 ms per guess. Kept identical on Android (VaultStore.kt) so both
# platforms resist cracking to the same degree.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1


def _private_dir() -> None:
    """The vault directory, owner-only (audit H13: it used to get the default
    umask, usually 0755, with its files at 0644 — while settings.json next
    door was already 0600). Tightened on every use, so an older vault gets
    fixed too."""
    _VAULT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(_VAULT_DIR, 0o700)
    for f in _VAULT_DIR.iterdir():
        if f.is_file() and not f.is_symlink():
            os.chmod(f, 0o600)


def _write_private(path: Path, data: bytes) -> None:
    """Write `data` to `path`, 0600 from the first byte, replaced atomically."""
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _get_or_create_salt() -> bytes:
    _private_dir()
    if _SALT_FILE.exists():
        return _SALT_FILE.read_bytes()
    salt = os.urandom(32)
    _write_private(_SALT_FILE, salt)
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

def _salted_hash(password: str, role: bytes) -> str:
    # The role's fixed salt goes in front of the random one, so a lock hash
    # can never pass as a decoy hash or the other way round.
    salt = os.urandom(16)
    return f"{_SALTED_PREFIX}{salt.hex()}${_derive_key(password, role + salt).hex()}"


def make_lock_hash(password: str) -> str:
    return _salted_hash(password, _LOCK_SALT)

def make_decoy_hash(password: str) -> str:
    return _salted_hash(password, _DECOY_SALT)


def _matches(password: str, stored_hash: str, salt: bytes) -> bool:
    """Compare against any of the hash schemes, in constant time.

    `salt` is the role's fixed salt: the whole salt of the legacy schemes, the
    prefix of a current hash's own random one. Constant time because a plain `==` on hex strings leaks how many
    leading characters matched, which is enough to reconstruct the stored
    digest one character at a time.
    """
    if stored_hash.startswith(_SALTED_PREFIX):
        try:
            salt_hex, digest = stored_hash[len(_SALTED_PREFIX):].split("$", 1)
            own_salt = bytes.fromhex(salt_hex)
        except ValueError:
            return False
        if not own_salt:
            return False
        return hmac.compare_digest(_derive_key(password, salt + own_salt).hex(), digest)
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
    """True for a lock/decoy hash in one of the fixed-salt schemes.

    Callers re-save the upgraded hash after a successful unlock, when the
    password is in hand — see MainWindow's vault unlock path.
    """
    return bool(stored_hash) and not stored_hash.startswith(_SALTED_PREFIX)


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
    _write_private(_VAULT_DIR / filename, _MAGIC_V2 + nonce + ct)


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
