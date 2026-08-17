"""Symmetric encryption for `content_source.config_encrypted`.

Same shape as `core/crypto.py`'s `DsnCipher` — Fernet, one instance per
process, built from a setting rather than derived — but a distinct class and
a distinct key (`MNEMOS_SOURCE_ENCRYPTION_KEY`, not
`MNEMOS_DSN_ENCRYPTION_KEY`). A connector's config (an S3 bucket/prefix, a
filesystem root, an HTTP allowlist) is a different secret than a datasource
DSN with a different rotation story, and a shared key would mean rotating one
forces rotating the other.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from mnemos.core.errors import ConfigurationError


class SourceConfigCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ConfigurationError(
                "source_encryption_key is not a valid Fernet key (32 url-safe base64-encoded bytes)"
            ) from exc

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ConfigurationError(
                "a content_source config could not be decrypted — the encryption "
                "key changed or the stored value is corrupt"
            ) from exc
