"""Session-password proof for native joins (auth v2, audit H6).

The v1 join sent SHA-256("haze-session-v1:" + password) in the hello. That
digest was the credential itself: whoever received it could join with it
without ever knowing the password. And a client sends it to whatever address
it was given — a lookalike .onion pasted into a chat collected a digest that
opened the real session, however strong the password was.

v2 sends nothing reusable. The host sends a fresh random challenge and the
client answers

    key   = PBKDF2-HMAC-SHA256(password, "haze-auth-v2:" + <host onion>, 200 000)
    proof = HMAC-SHA256(key, "haze-auth-v2|" + challenge + "|" + client public key)

The onion address the CLIENT connected to is in the key, so an answer given to
a lookalike address is worthless at the real one (not replayable, not
relayable); the challenge makes every answer single-use; and what a fake host
does collect costs 200 000 PBKDF2 rounds per guess to attack offline instead
of one SHA-256.

The same construction is in haze-mobile (crypto/SessionAuth.kt); both sides
must agree byte for byte.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

VERSION = 2
ITERATIONS = 200_000
_SALT_PREFIX = b"haze-auth-v2:"
_PROOF_PREFIX = "haze-auth-v2|"


def onion_id(address: str) -> str:
    """The canonical form of an onion address: "<56 chars>.onion", lowercase.

    Users paste addresses with or without scheme, ".onion", a trailing slash
    or a port; host and client must derive the same key from all of them.
    """
    a = (address or "").strip().lower()
    if "://" in a:
        a = a.split("://", 1)[1]
    for sep in "/?#":
        a = a.split(sep, 1)[0]
    a = a.split(":", 1)[0]
    a = a.removesuffix(".onion")
    return f"{a}.onion" if a else ""


def auth_key(password: str, onion: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"),
        _SALT_PREFIX + onion_id(onion).encode("ascii"), ITERATIONS, 32)


def new_challenge() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def proof(key: bytes, challenge: str, client_pub_b64: str) -> str:
    msg = f"{_PROOF_PREFIX}{challenge}|{client_pub_b64}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()
