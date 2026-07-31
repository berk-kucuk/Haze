"""
End-to-end encryption for browser clients.

Browsers cannot speak the native protocol: WebCrypto has no ChaCha20-Poly1305,
and older Tor Browser builds (Firefox ESR) have no X25519 either. So web clients
get the same construction with the primitives a browser actually has —

    key agreement : X25519, or ECDH P-256 where X25519 is unavailable
    derivation    : HKDF-SHA256
    payloads      : AES-256-GCM

— and the host, which already relays every message, converts between that and
the native ChaCha20-Poly1305 stream.

The AEAD key is HKDF'd from the group session key rather than being the group
key itself, so the same 32 bytes are never used with two different ciphers.

WHAT THIS DOES AND DOES NOT BUY
    It removes browser plaintext from the host's HTTP/WebSocket layer, so a bug
    or a memory capture there yields ciphertext.

    It does NOT make a browser guest as safe as the app. The host serves the
    JavaScript that performs this encryption, so a malicious or compromised host
    can serve a page that leaks the key. An installed client runs code the host
    cannot change. That gap is inherent to running a chat client in a page and
    no amount of crypto in that page closes it.
"""

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

# Domain separation: distinct labels so the handshake key, the traffic key and
# the native session key can never collide.
_HANDSHAKE_INFO = b"haze-web-handshake-v1"
_TRAFFIC_INFO = b"haze-web-aead-v1"

ALG_X25519 = "X25519"
ALG_P256 = "P-256"
SUPPORTED_ALGS = (ALG_X25519, ALG_P256)


class WebCryptoError(Exception):
    """Handshake or payload could not be processed."""


def derive_traffic_key(session_key: bytes) -> bytes:
    """The AES-GCM key browser clients share, derived from the group key."""
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_TRAFFIC_INFO
    ).derive(bytes(session_key))


def _hkdf_handshake(shared: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_HANDSHAKE_INFO
    ).derive(shared)


def wrap_traffic_key(client_pub_b64: str, alg: str, traffic_key: bytes) -> dict:
    """Host side of the handshake.

    Generates an ephemeral key for this one connection, agrees a secret with the
    browser's public key, and seals `traffic_key` under it. Returns the fields
    to send back: the host's public key plus the sealed traffic key.
    """
    if alg not in SUPPORTED_ALGS:
        raise WebCryptoError(f"unsupported key agreement: {alg!r}")

    try:
        peer_raw = base64.b64decode(client_pub_b64, validate=True)
    except Exception as exc:
        raise WebCryptoError("malformed public key") from exc

    try:
        if alg == ALG_X25519:
            private = X25519PrivateKey.generate()
            peer = X25519PublicKey.from_public_bytes(peer_raw)
            shared = private.exchange(peer)
            host_pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        else:
            private = ec.generate_private_key(ec.SECP256R1())
            peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), peer_raw)
            shared = private.exchange(ec.ECDH(), peer)
            # WebCrypto's "raw" export for P-256 is the uncompressed point.
            host_pub = private.public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )
    except WebCryptoError:
        raise
    except Exception as exc:
        raise WebCryptoError("key agreement failed") from exc

    wrap_key = _hkdf_handshake(shared)
    nonce = os.urandom(12)
    sealed = AESGCM(wrap_key).encrypt(nonce, traffic_key, None)
    return {
        "pubkey": base64.b64encode(host_pub).decode(),
        "alg": alg,
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(sealed).decode(),
    }


def encrypt(traffic_key: bytes, payload: dict) -> dict:
    """Seal one event for the browser."""
    nonce = os.urandom(12)
    ct = AESGCM(traffic_key).encrypt(nonce, json.dumps(payload).encode(), None)
    return {
        "type": "encrypted",
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ct).decode(),
    }


def decrypt(traffic_key: bytes, envelope: dict) -> dict:
    """Open one event from the browser. Raises WebCryptoError on any tampering."""
    try:
        nonce = base64.b64decode(str(envelope.get("nonce", "")), validate=True)
        ct = base64.b64decode(str(envelope.get("ciphertext", "")), validate=True)
        plaintext = AESGCM(traffic_key).decrypt(nonce, ct, None)
        data = json.loads(plaintext.decode())
    except Exception as exc:
        raise WebCryptoError("could not decrypt payload") from exc
    if not isinstance(data, dict):
        raise WebCryptoError("payload was not an object")
    return data
