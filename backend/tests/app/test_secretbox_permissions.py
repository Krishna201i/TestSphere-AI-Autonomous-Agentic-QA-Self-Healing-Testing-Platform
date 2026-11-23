"""Local development encryption keys must not leak through file permissions."""

import os
import stat

import pytest
from cryptography.fernet import Fernet

from app import secretbox
from app.config import settings


@pytest.fixture
def local_key(monkeypatch, tmp_path):
    key_path = tmp_path / "data" / ".token_key"
    monkeypatch.setattr(secretbox, "_LOCAL_KEY", key_path)
    monkeypatch.setattr(secretbox, "_hosted", lambda: False)
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", "")
    return key_path


def test_first_use_creates_key_and_reuses_it(local_key):
    one = secretbox.encrypt("secret-value")
    assert secretbox.decrypt(one) == "secret-value"
    key_before = local_key.read_bytes()
    assert len(key_before) == 44  # Fernet's URL-safe base64 key
    assert secretbox.decrypt(secretbox.encrypt("second-value")) == "second-value"
    assert local_key.read_bytes() == key_before


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_local_key_only_readable_by_owner(local_key):
    secretbox.encrypt("secret-value")
    assert stat.S_IMODE(local_key.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_existing_key_permissions_are_repaired_without_rotation(local_key):
    local_key.parent.mkdir(parents=True)
    original = Fernet.generate_key()
    local_key.write_bytes(original)
    local_key.chmod(0o644)
    assert secretbox.decrypt(secretbox.encrypt("test")) == "test"
    assert local_key.read_bytes() == original
    assert stat.S_IMODE(local_key.stat().st_mode) == 0o600
