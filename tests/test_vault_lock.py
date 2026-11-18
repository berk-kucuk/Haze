"""Vault lock / decoy hashes carry a salt of their own (audit H8), and the
broken in-place string wipe is gone (H7).

The old hashes used one fixed salt for every installation, so a single
precomputed table attacked every user's lock at once.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_HOME = tempfile.mkdtemp(prefix="haze-test-home-")
os.environ["HOME"] = _HOME
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from haze.storage import vault  # noqa: E402

PW = "correct horse battery staple"


class SaltTests(unittest.TestCase):
    def test_every_hash_has_its_own_salt(self):
        a, b = vault.make_lock_hash(PW), vault.make_lock_hash(PW)
        self.assertNotEqual(a, b, "two users with the same password got the same hash")
        self.assertTrue(a.startswith("scrypt2$"))
        self.assertNotEqual(vault.make_decoy_hash(PW).split("$")[1], a.split("$")[1])

    def test_verify(self):
        lock, decoy = vault.make_lock_hash(PW), vault.make_decoy_hash("duress")
        self.assertTrue(vault.check_lock(PW, lock))
        self.assertFalse(vault.check_lock("wrong", lock))
        self.assertTrue(vault.check_decoy("duress", decoy))
        self.assertFalse(vault.check_decoy(PW, decoy))
        self.assertFalse(vault.is_legacy_hash(lock))
        # A lock hash is never a valid decoy hash, nor the reverse.
        self.assertFalse(vault.check_decoy(PW, vault.make_lock_hash(PW)))
        self.assertFalse(vault.check_lock("duress", decoy))

    def test_older_hashes_still_open_and_are_flagged(self):
        old_scrypt = vault._scrypt_hex(PW, vault._LOCK_SALT)
        old_pbkdf2 = vault._pbkdf2_hex(PW, vault._LOCK_SALT)
        old_decoy = vault._scrypt_hex("duress", vault._DECOY_SALT)
        for h in (old_scrypt, old_pbkdf2):
            self.assertTrue(vault.check_lock(PW, h), "an existing user was locked out")
            self.assertFalse(vault.check_lock("wrong", h))
            self.assertTrue(vault.is_legacy_hash(h))
        self.assertTrue(vault.check_decoy("duress", old_decoy))
        self.assertTrue(vault.is_legacy_hash(old_decoy))

    def test_malformed_hash_never_matches(self):
        for h in ("scrypt2$", "scrypt2$zz$00", "scrypt2$$abcd", "scrypt2$00"):
            self.assertFalse(vault.check_lock(PW, h), h)

    def test_decoy_unlock_upgrades_the_decoy_hash(self):
        """_VaultPopup._do_unlock: the decoy password upgrades the decoy hash."""
        from haze.ui import main_window as mw
        saved = []
        orig = mw._app_settings.save
        mw._app_settings.save = saved.append
        try:
            settings = {"vault_decoy_hash": vault._scrypt_hex("duress", vault._DECOY_SALT),
                        "vault_lock_hash": vault._scrypt_hex(PW, vault._LOCK_SALT)}
            mw._VaultPopup._upgrade_legacy_hashes(None, "duress", settings, key="vault_decoy_hash")
            mw._VaultPopup._upgrade_legacy_hashes(None, PW, settings)
        finally:
            mw._app_settings.save = orig
        self.assertTrue(settings["vault_decoy_hash"].startswith("scrypt2$"))
        self.assertTrue(vault.check_decoy("duress", settings["vault_decoy_hash"]))
        self.assertTrue(vault.check_lock(PW, settings["vault_lock_hash"]))
        self.assertFalse(vault.is_legacy_hash(settings["vault_lock_hash"]))
        self.assertEqual(len(saved), 2)


class WipeStringTests(unittest.TestCase):
    def test_the_crashing_wipe_is_gone(self):
        from haze.secure import memory
        self.assertFalse(hasattr(memory, "wipe_string"))
        buf = bytearray(b"secret")
        memory.secure_wipe_bytearray(buf)
        self.assertEqual(buf, bytearray(6))


if __name__ == "__main__":
    unittest.main(verbosity=2)
