"""The tool boundary is deterministic policy, not model judgement."""

from __future__ import annotations

import pytest

from mnemos.core.types import TrustTier
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

