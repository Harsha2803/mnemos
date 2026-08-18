"""Frozen records that cross the MCP feature's application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mnemos.core.types import InvocationStatus, JsonValue, TrustTier
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.tools.domain.ids import (
    McpGrantId,
    McpInvocationId,
    McpServerId,
    McpToolId,
)


@dataclass(frozen=True, slots=True)
class McpServerRecord:
    id: McpServerId
    org_id: OrgId
    slug: str
    name: str
    description: str | None
    endpoint: str
    is_enabled: bool
    min_trust_tier: TrustTier
    requires_approval: bool
    last_discovered_at: datetime | None
    health_status: str | None


@dataclass(frozen=True, slots=True)
class McpToolRecord:
    id: McpToolId
    org_id: OrgId
    server_id: McpServerId
    name: str
    description: str | None
    input_schema: dict[str, JsonValue]
    is_enabled: bool
    requires_approval: bool
    is_mutating: bool


@dataclass(frozen=True, slots=True)
class McpGrantRecord:
    id: McpGrantId
    org_id: OrgId
    tool_id: McpToolId
    user_id: UserId
    granted_by: UserId | None
    auto_approve: bool
    expires_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class McpCredentialState:
    """Display-safe credential metadata; the secret never enters a read model."""

    server_id: McpServerId
    user_id: UserId
    scheme: str
    expires_at: datetime | None
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class McpInvocationRecord:
    id: McpInvocationId
    org_id: OrgId
    tool_id: McpToolId
    user_id: UserId
    message_id: str | None
    arguments: dict[str, JsonValue]
    status: InvocationStatus
    caller_trust_tier: TrustTier
    denied_reason: str | None
    offending_bundle_item_id: str | None
    offending_source: str | None
    approved_by: UserId | None
    approved_at: datetime | None
    result: dict[str, JsonValue]
    duration_ms: int | None
    error_code: str | None
    created_at: datetime
