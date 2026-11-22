"""
TestSphere-AI — Encryption for stored third-party tokens (GitHub, ...).

Tokens are encrypted with Fernet (AES-128-CBC + HMAC) under
``TOKEN_ENCRYPTION_KEY`` before they reach the database, so a database
export alone does not leak them.  Hosted servers must set the key; local
development generates one in ``data/.token_key`` on first use.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from backend.config import _hosted, settings

_LOCAL_KEY = Path("data") / ".token_key"


class SecretBoxError(RuntimeError):
    pass


def _key() -> bytes:
    if settings.TOKEN_ENCRYPTION_KEY:
        return settings.TOKEN_ENCRYPTION_KEY.encode()
    if _hosted():
        raise SecretBoxError("Set TOKEN_ENCRYPTION_KEY on the server to connect integrations "
                             "(generate one with: python -c \"from cryptography.fernet import Fernet; "
                             "print(Fernet.generate_key().decode())\").")
    if not _LOCAL_KEY.is_file():
        _LOCAL_KEY.parent.mkdir(parents=True, exist_ok=True)
        _LOCAL_KEY.write_bytes(Fernet.generate_key())
    return _LOCAL_KEY.read_bytes().strip()


def encrypt(value: str) -> str:
    try:
        return Fernet(_key()).encrypt(value.encode()).decode()
    except ValueError as exc:
        raise SecretBoxError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def decrypt(value: str) -> str:
    try:
        return Fernet(_key()).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise SecretBoxError("A stored token could not be decrypted (the encryption key changed). "
                             "Connect the integration again.") from exc
