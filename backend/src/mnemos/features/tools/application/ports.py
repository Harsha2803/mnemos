"""Ports owned by the MCP application layer."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from mnemos.core.types import InvocationStatus, JsonValue, TrustTier
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.tools.domain import (
    McpCredentialState,
    McpGrantRecord,
    McpInvocationId,
    McpInvocationRecord,
    McpServerId,
    McpServerRecord,
    McpToolId,
    McpToolRecord,
)


class ToolRepository(Protocol):
    async def create_server(
        self,
        *,
        org_id: OrgId,
        slug: str,
        name: str,
        description: str | None,
        endpoint: str,
        min_trust_tier: TrustTier,
        requires_approval: bool,
    ) -> McpServerRecord: ...

    async def list_servers(self, *, org_id: OrgId) -> Sequence[McpServerRecord]: ...

    async def get_server(
        self, *, org_id: OrgId, server_id: McpServerId
    ) -> McpServerRecord | None: ...

    async def replace_discovered_tools(
        self,
        *,
        org_id: OrgId,
        server_id: McpServerId,
        tools: Sequence[McpToolRecord],
        discovered_at: datetime,
    ) -> Sequence[McpToolRecord]: ...

    async def list_tools(
        self, *, org_id: OrgId, server_id: McpServerId | None = None
    ) -> Sequence[McpToolRecord]: ...

    async def get_tool(self, *, org_id: OrgId, tool_id: McpToolId) -> McpToolRecord | None: ...

    async def put_credential(
        self,
        *,
        org_id: OrgId,
        server_id: McpServerId,
        user_id: UserId,
        scheme: str,
        secret_encrypted: bytes,
        expires_at: datetime | None,
    ) -> McpCredentialState: ...

    async def get_credential_state(
        self, *, org_id: OrgId, server_id: McpServerId, user_id: UserId
    ) -> McpCredentialState | None: ...

    async def get_encrypted_credential(
        self, *, org_id: OrgId, server_id: McpServerId, user_id: UserId
    ) -> tuple[str, bytes] | None: ...

    async def put_grant(
        self,
        *,
        org_id: OrgId,
        tool_id: McpToolId,
        user_id: UserId,
        granted_by: UserId,
        auto_approve: bool,
        expires_at: datetime | None,
    ) -> McpGrantRecord: ...

    async def get_grant(
        self, *, org_id: OrgId, tool_id: McpToolId, user_id: UserId, at: datetime
    ) -> McpGrantRecord | None: ...

    async def create_invocation(
        self,
        *,
        org_id: OrgId,
        tool_id: McpToolId,
        user_id: UserId,
        arguments: dict[str, JsonValue],
        status: InvocationStatus,
        caller_trust_tier: TrustTier,
        denied_reason: str | None,
        offending_bundle_item_id: str | None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> McpInvocationRecord: ...

    async def get_invocation(
        self, *, org_id: OrgId, invocation_id: McpInvocationId
    ) -> McpInvocationRecord | None: ...

    async def transition_invocation(
        self,
        *,
        org_id: OrgId,
        invocation_id: McpInvocationId,
        expected: InvocationStatus,
        status: InvocationStatus,
        approved_by: UserId | None = None,
        approved_at: datetime | None = None,
        result: dict[str, JsonValue] | None = None,
        duration_ms: int | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        denied_reason: str | None = None,
    ) -> McpInvocationRecord | None: ...

    async def list_invocations(
        self, *, org_id: OrgId, user_id: UserId
    ) -> Sequence[McpInvocationRecord]: ...

    async def get_bundle_item_source(self, *, org_id: OrgId, bundle_item_id: str) -> str | None: ...
