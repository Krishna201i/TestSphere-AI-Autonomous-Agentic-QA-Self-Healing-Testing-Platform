"""
TestSphere-AI — Encryption for stored third-party tokens (GitHub, ...).

Tokens are encrypted with Fernet (AES-128-CBC + HMAC) under
``TOKEN_ENCRYPTION_KEY`` before they reach the database, so a database
export alone does not leak them.  Hosted servers must set the key; local
development generates one in ``data/.token_key`` on first use.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import _hosted, settings

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
    # An integration token is only as private as its encryption key.  A
    # regular write_bytes() creates the file with the host's umask (often
    # world-readable).  Create it exclusively with owner-only permissions so
    # concurrent first starts never overwrite one another's keys.
    if not _LOCAL_KEY.is_file():
        _LOCAL_KEY.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(_LOCAL_KEY, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass  # Another process created the key; reuse it.
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(Fernet.generate_key())

    # Lock down keys created by older TestSphere versions too.
    if os.name == "posix":
        _LOCAL_KEY.chmod(0o600)
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
