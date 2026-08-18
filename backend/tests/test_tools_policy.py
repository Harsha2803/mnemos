"""The tool boundary is deterministic policy, not model judgement."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from mnemos.core.config import Settings
from mnemos.core.errors import ConfigurationError
from mnemos.core.types import TrustTier
from mnemos.features.tools.adapters.crypto import ToolCredentialCipher
from mnemos.features.tools.domain.policy import (
    GRANT_DENIED,
    LIVE_ROLE_DENIED,
    TRUST_DENIED,
    authorize_tool_call,
)


@pytest.mark.parametrize(
    ("live_role", "grant", "tier", "expected"),
    [
        (False, True, TrustTier.USER, LIVE_ROLE_DENIED),
        (True, False, TrustTier.USER, GRANT_DENIED),
        (True, True, TrustTier.RETRIEVED, TRUST_DENIED),
        (True, True, TrustTier.USER, None),
        (True, True, TrustTier.OPERATOR, None),
    ],
)
def test_authorization_requires_live_role_grant_and_trust(
    live_role: bool,
    grant: bool,
    tier: TrustTier,
    expected: str | None,
) -> None:
    decision = authorize_tool_call(
        live_role_allows=live_role,
        has_active_grant=grant,
        motivating_tier=tier,
        required_tier=TrustTier.USER,
    )
    assert decision.allowed is (expected is None)
    assert decision.reason == expected


def test_production_rejects_the_published_tool_encryption_key() -> None:
    with pytest.raises(ValidationError, match="MNEMOS_TOOL_ENCRYPTION_KEY"):
        Settings(
            env="production",
            jwt_secret="production-jwt-secret-at-least-32-bytes",
            dsn_encryption_key=Fernet.generate_key().decode("ascii"),
            source_encryption_key=Fernet.generate_key().decode("ascii"),
        )


def test_tool_cipher_rejects_a_malformed_key() -> None:
    with pytest.raises(ConfigurationError, match="valid Fernet key"):
        ToolCredentialCipher("not-a-fernet-key")
