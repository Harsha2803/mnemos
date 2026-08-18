"""Pure authorization policy for a proposed MCP invocation."""

from __future__ import annotations

from dataclasses import dataclass

from mnemos.core.types import TrustTier

LIVE_ROLE_DENIED = "live_role_forbids_tool"
GRANT_DENIED = "grant_missing_or_expired"
TRUST_DENIED = "trust_tier_insufficient"


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    allowed: bool
    reason: str | None


def authorize_tool_call(
    *,
    live_role_allows: bool,
    has_active_grant: bool,
    motivating_tier: TrustTier,
    required_tier: TrustTier,
) -> ToolAuthorizationDecision:
    """Deny unless the live role, standing grant, and trust floor all pass."""
    if not live_role_allows:
        return ToolAuthorizationDecision(allowed=False, reason=LIVE_ROLE_DENIED)
    if not has_active_grant:
        return ToolAuthorizationDecision(allowed=False, reason=GRANT_DENIED)
    if motivating_tier < required_tier:
        return ToolAuthorizationDecision(allowed=False, reason=TRUST_DENIED)
    return ToolAuthorizationDecision(allowed=True, reason=None)

