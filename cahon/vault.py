"""Encrypted password vault.

Passwords are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using a key
derived from the master password with scrypt. Only the encrypted blob is stored
in the database; the master password and derived key are never written to disk.
Titles, usernames and URLs stay searchable while the vault is locked.
"""

from __future__ import annotations

import base64
import os
import threading
import time

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .db import Database

_CHECK_TOKEN = b"cahon-vault-check"
SCRYPT_N = 2**15


class VaultError(Exception):
    pass


class VaultLocked(VaultError):
    pass


def derive_key(master_password: str, salt: bytes, n: int = SCRYPT_N) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=n, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


class Vault:
    def __init__(self, db: Database, auto_lock_seconds: int = 900, scrypt_n: int = SCRYPT_N):
        self.db = db
        self.auto_lock_seconds = auto_lock_seconds
        self.scrypt_n = scrypt_n
        self._fernet: Fernet | None = None
        self._last_used = 0.0
        self._lock = threading.Lock()

    @property
    def is_set_up(self) -> bool:
        return self.db.get_meta("vault") is not None

    @property
    def is_unlocked(self) -> bool:
        with self._lock:
            if self._fernet and time.time() - self._last_used > self.auto_lock_seconds:
                self._fernet = None
            return self._fernet is not None

    def setup(self, master_password: str) -> None:
        if self.is_set_up:
            raise VaultError("vault already set up")
        if len(master_password) < 8:
            raise VaultError("master password must be at least 8 characters")
        salt = os.urandom(16)
        fernet = Fernet(derive_key(master_password, salt, self.scrypt_n))
        self.db.set_meta(
            "vault",
            {
                "salt": base64.b64encode(salt).decode(),
                "n": self.scrypt_n,
                "check": fernet.encrypt(_CHECK_TOKEN).decode(),
            },
        )
        with self._lock:
            self._fernet = fernet
            self._last_used = time.time()

    def unlock(self, master_password: str) -> bool:
        meta = self.db.get_meta("vault")
        if meta is None:
            raise VaultError("vault not set up")
        salt = base64.b64decode(meta["salt"])
        fernet = Fernet(derive_key(master_password, salt, meta.get("n", SCRYPT_N)))
        try:
            if fernet.decrypt(meta["check"].encode()) != _CHECK_TOKEN:
                return False
        except InvalidToken:
            return False
        with self._lock:
            self._fernet = fernet
            self._last_used = time.time()
        return True

    def lock(self) -> None:
        with self._lock:
            self._fernet = None

    def _get(self) -> Fernet:
        if not self.is_unlocked:
            raise VaultLocked("vault is locked")
        with self._lock:
            self._last_used = time.time()
            assert self._fernet is not None
            return self._fernet

    def encrypt(self, plaintext: str) -> bytes:
        return self._get().encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._get().decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise VaultError("could not decrypt secret") from exc
