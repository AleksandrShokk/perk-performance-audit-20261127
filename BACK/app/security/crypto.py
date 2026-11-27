import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
# Unknown users incur the same expensive password verification as known users.
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
# Each Argon2 operation holds 64 MiB. A bounded number of concurrent operations per process
# keeps a login burst from exhausting the container's memory; the rest fail fast with 503.
PASSWORD_CONCURRENCY = int(os.environ.get("PASSWORD_HASH_CONCURRENCY", "4"))
PASSWORD_SLOTS = threading.BoundedSemaphore(PASSWORD_CONCURRENCY)
PASSWORD_WAIT_SECONDS = 5


@contextmanager
def password_slot():
    if not PASSWORD_SLOTS.acquire(timeout=PASSWORD_WAIT_SECONDS):
        raise HTTPException(
            503, "Сервис входа перегружен. Повторите через несколько секунд.", {"Retry-After": "5"}
        )
    try:
        yield
    finally:
        PASSWORD_SLOTS.release()


def hash_password(password: str) -> str:
    with password_slot():
        return PASSWORD_HASHER.hash(password)


class SecretVault:
    def __init__(self, path: Path):
        config = json.loads(path.read_text(encoding="utf-8"))
        self.active_key = config["active_key"]
        self.keys = {
            name: base64.b64decode(value, validate=True) for name, value in config["keys"].items()
        }
        self.hmac_key = base64.b64decode(config["token_hmac_key"], validate=True)
        if self.active_key not in self.keys or any(len(key) != 32 for key in self.keys.values()):
            raise ValueError("Invalid encryption key configuration")
        if len(self.hmac_key) != 32:
            raise ValueError("Invalid authentication key configuration")

    def seal(self, value: str, context: str) -> str:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self.keys[self.active_key]).encrypt(
            nonce, value.encode(), context.encode()
        )
        return self.active_key + "." + base64.urlsafe_b64encode(nonce + ciphertext).decode()

    def open(self, value: str, context: str) -> str:
        key_id, encoded = value.split(".", 1)
        data = base64.urlsafe_b64decode(encoded)
        return AESGCM(self.keys[key_id]).decrypt(data[:12], data[12:], context.encode()).decode()

    def digest(self, purpose: str, value: str) -> str:
        return hmac.new(self.hmac_key, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def verify_password(encoded: str, supplied: str) -> bool:
    with password_slot():
        try:
            return PASSWORD_HASHER.verify(encoded, supplied)
        except VerificationError, InvalidHashError:
            return False
