"""Fernet encryption for per-user MCP credentials."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from mnemos.core.errors import ConfigurationError


class ToolCredentialCipher:
    """Keep tool credentials under a key distinct from other stored secrets."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ConfigurationError(
                "tool_encryption_key is not a valid Fernet key (32 url-safe base64-encoded bytes)"
            ) from exc

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ConfigurationError(
                "an MCP credential could not be decrypted — the encryption key changed "
                "or the stored value is corrupt"
            ) from exc
