import os
import json
import base64

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


class SessionCrypto:
    """
    Per-connection crypto state.

    Flow (host side):
      1. generate_session_key() — called once by host, shared with all clients
      2. For each connecting client: derive_wrap_key(client_pub) → wrap_session_key()
         → send encrypted session key to client

    Flow (client side):
      1. exchange: send own public_key_b64, receive host pubkey + wrapped session key
      2. derive_wrap_key(host_pub) → unwrap_session_key(...)
      3. encrypt() / decrypt() with shared session key
    """

    def __init__(self) -> None:
        self._private_key = X25519PrivateKey.generate()
        self._session_key: bytearray | None = None

    @property
    def public_key_b64(self) -> str:
        raw = self._private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    def generate_session_key(self) -> None:
        self._session_key = bytearray(os.urandom(32))

    def set_session_key(self, key_bytes: bytes) -> None:
        self._session_key = bytearray(key_bytes)

    # ------------------------------------------------------------------
    # Key wrap / unwrap (used during handshake only)
    # ------------------------------------------------------------------

    def _derive_wrap_key(self, peer_pub_b64: str) -> bytes:
        peer_raw = base64.b64decode(peer_pub_b64)
        peer_pub = X25519PublicKey.from_public_bytes(peer_raw)
        shared = self._private_key.exchange(peer_pub)
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"haze-protocol-v1",
        ).derive(shared)

    def wrap_session_key(self, peer_pub_b64: str) -> dict:
        """Return dict with nonce+ciphertext (base64) for sending over wire."""
        wrap_key = self._derive_wrap_key(peer_pub_b64)
        nonce = os.urandom(12)
        ct = ChaCha20Poly1305(wrap_key).encrypt(nonce, bytes(self._session_key), None)
        return {
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
        }

    def unwrap_session_key(self, peer_pub_b64: str, nonce_b64: str, ct_b64: str) -> None:
        wrap_key = self._derive_wrap_key(peer_pub_b64)
        nonce = base64.b64decode(nonce_b64)
        ct = base64.b64decode(ct_b64)
        raw = ChaCha20Poly1305(wrap_key).decrypt(nonce, ct, None)
        self._session_key = bytearray(raw)

    # ------------------------------------------------------------------
    # Message encryption / decryption
    # ------------------------------------------------------------------

    def encrypt(self, payload: dict) -> dict:
        nonce = os.urandom(12)
        plaintext = json.dumps(payload).encode()
        ct = ChaCha20Poly1305(bytes(self._session_key)).encrypt(nonce, plaintext, None)
        return {
            "type": "encrypted",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
        }

    def decrypt(self, envelope: dict) -> dict:
        nonce = base64.b64decode(envelope["nonce"])
        ct = base64.b64decode(envelope["ciphertext"])
        plaintext = ChaCha20Poly1305(bytes(self._session_key)).decrypt(nonce, ct, None)
        return json.loads(plaintext.decode())

    # ------------------------------------------------------------------
    # Secure wipe
    # ------------------------------------------------------------------

    def wipe(self) -> None:
        if self._session_key is not None:
            for i in range(len(self._session_key)):
                self._session_key[i] = 0
            self._session_key = None
