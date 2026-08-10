"""Symmetric encryption for secrets stored at rest — currently, datasource DSNs.

Fernet (AES-128-CBC + HMAC-SHA256, both authenticated) rather than a hand-rolled
scheme: it is a single well-reviewed primitive from `cryptography`, and the
security-critical mistake in this codebase would be inventing one instead of
using it.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from mnemos.core.errors import ConfigurationError


class DsnCipher:
    """Encrypts and decrypts a datasource connection string.

    One instance per process, built from `Settings.dsn_encryption_key` — the
    same key must decrypt what an earlier process encrypted, so it is
    configuration, not a value generated at import time.
    """

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ConfigurationError(
                "dsn_encryption_key is not a valid Fernet key (32 url-safe base64-encoded bytes)"
            ) from exc

    def encrypt(self, dsn: str) -> bytes:
        return self._fernet.encrypt(dsn.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ConfigurationError(
                "a datasource DSN could not be decrypted — the encryption key changed "
                "or the stored value is corrupt"
            ) from exc
