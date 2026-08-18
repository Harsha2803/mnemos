"""One durable MCP invocation, including approval and boundary re-authorization."""

from __future__ import annotations

import json
import time
from datetime import datetime

from mnemos.core.clock import Clock
from mnemos.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from mnemos.core.logging import get_logger
from mnemos.core.types import InvocationStatus, JsonValue, TrustTier
from mnemos.features.chat.domain import ChatMessageId
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.features.identity.domain import Permission
from mnemos.features.tools.adapters.crypto import ToolCredentialCipher
from mnemos.features.tools.adapters.mcp_http import StreamableHttpMcpClient, validate_arguments
from mnemos.features.tools.application.ports import ToolRepository
from mnemos.features.tools.domain import (
    McpGrantRecord,
    McpInvocationId,
    McpInvocationRecord,
    McpServerRecord,
    McpToolId,
    McpToolRecord,
)
from mnemos.features.tools.domain.policy import (
    TRUST_DENIED,
    ToolAuthorizationDecision,
    authorize_tool_call,
)

log = get_logger(__name__)
TOOL_INVOKE = Permission.require("tool", "invoke")
TOOL_MANAGE = Permission.require("tool", "manage")


class ToolInvocationService:
    def __init__(
        self,
        *,
        repository: ToolRepository,
        client: StreamableHttpMcpClient,
        cipher: ToolCredentialCipher,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._client = client
        self._cipher = cipher
        self._clock = clock

    async def grant_to_self(
        self,
        *,
        caller: AuthenticatedCaller,
        tool_id: McpToolId,
        auto_approve: bool,
        expires_at: datetime | None = None,
    ) -> McpGrantRecord:
        if not caller.principal.has_permission(TOOL_MANAGE):
            raise AuthorizationError("you are not allowed to manage tool grants")
        tool = await self._repository.get_tool(org_id=caller.principal.org_id, tool_id=tool_id)
        if tool is None:
            raise NotFoundError("tool not found")
        return await self._repository.put_grant(
            org_id=caller.principal.org_id,
            tool_id=tool_id,
            user_id=caller.principal.principal_id,
            granted_by=caller.principal.principal_id,
            auto_approve=auto_approve,
            expires_at=expires_at,
        )

    async def propose(
        self,
        *,
        caller: AuthenticatedCaller,
        tool_id: McpToolId,
        arguments: dict[str, JsonValue],
        motivating_tier: TrustTier,
        offending_bundle_item_id: str | None = None,
    ) -> McpInvocationRecord:
        tool, server = await self._load_tool_server(caller=caller, tool_id=tool_id)
        grant, decision = await self._authorize(
            caller=caller,
            tool=tool,
            server=server,
            motivating_tier=motivating_tier,
        )
        if not decision.allowed:
            source = await self._validate_offending_source(
                caller=caller,
                decision=decision,
                offending_bundle_item_id=offending_bundle_item_id,
            )
            invocation = await self._repository.create_invocation(
                org_id=caller.principal.org_id,
                tool_id=tool.id,
                user_id=caller.principal.principal_id,
                arguments=arguments,
                status=InvocationStatus.DENIED,
                caller_trust_tier=motivating_tier,
                denied_reason=decision.reason,
                offending_bundle_item_id=offending_bundle_item_id if source is not None else None,
            )
            log.info(
                "tool.invocation_denied",
                invocation_id=str(invocation.id),
                reason=decision.reason,
                offending_source=source,
            )
            return invocation

        try:
            validate_arguments(input_schema=tool.input_schema, arguments=arguments)
        except ValidationError as exc:
            return await self._repository.create_invocation(
                org_id=caller.principal.org_id,
                tool_id=tool.id,
                user_id=caller.principal.principal_id,
                arguments=arguments,
                status=InvocationStatus.FAILED,
                caller_trust_tier=motivating_tier,
                denied_reason=None,
                offending_bundle_item_id=None,
                error_code="invalid_arguments",
                error_detail=exc.message,
            )

        if grant is None:  # pragma: no cover - an allowed decision implies a grant
            raise RuntimeError("authorization allowed a tool call without a grant")
        approval_required = (
            tool.is_mutating
            or tool.requires_approval
            or server.requires_approval
            or not grant.auto_approve
        )
        invocation = await self._repository.create_invocation(
            org_id=caller.principal.org_id,
            tool_id=tool.id,
            user_id=caller.principal.principal_id,
            arguments=arguments,
            status=(
                InvocationStatus.PENDING_APPROVAL
                if approval_required
                else InvocationStatus.APPROVED
            ),
            caller_trust_tier=motivating_tier,
            denied_reason=None,
            offending_bundle_item_id=None,
        )
        if approval_required:
            log.info("tool.invocation_proposed", invocation_id=str(invocation.id))
            return invocation
        return await self._dispatch(caller=caller, invocation=invocation, tool=tool, server=server)

    async def approve(
        self, *, caller: AuthenticatedCaller, invocation_id: McpInvocationId
    ) -> McpInvocationRecord:
        invocation = await self._owned_pending(caller=caller, invocation_id=invocation_id)
        tool, server = await self._load_tool_server(caller=caller, tool_id=invocation.tool_id)
        _, decision = await self._authorize(
            caller=caller,
            tool=tool,
            server=server,
            motivating_tier=invocation.caller_trust_tier,
        )
        if not decision.allowed:
            denied = await self._repository.transition_invocation(
                org_id=caller.principal.org_id,
                invocation_id=invocation.id,
                expected=InvocationStatus.PENDING_APPROVAL,
                status=InvocationStatus.DENIED,
                denied_reason=decision.reason,
            )
            if denied is None:
                raise ConflictError("the invocation is no longer awaiting approval")
            await self._sync_message(tool=tool, invocation=denied)
            return denied
        approved_at = self._clock.now()
        approved = await self._repository.transition_invocation(
            org_id=caller.principal.org_id,
            invocation_id=invocation.id,
            expected=InvocationStatus.PENDING_APPROVAL,
            status=InvocationStatus.APPROVED,
            approved_by=caller.principal.principal_id,
            approved_at=approved_at,
        )
        if approved is None:
            raise ConflictError("the invocation is no longer awaiting approval")
        return await self._dispatch(caller=caller, invocation=approved, tool=tool, server=server)

    async def deny(
        self, *, caller: AuthenticatedCaller, invocation_id: McpInvocationId
    ) -> McpInvocationRecord:
        invocation = await self._owned_pending(caller=caller, invocation_id=invocation_id)
        tool, _ = await self._load_tool_server(caller=caller, tool_id=invocation.tool_id)
        denied = await self._repository.transition_invocation(
            org_id=caller.principal.org_id,
            invocation_id=invocation.id,
            expected=InvocationStatus.PENDING_APPROVAL,
            status=InvocationStatus.DENIED,
            approved_by=caller.principal.principal_id,
            approved_at=self._clock.now(),
            denied_reason="user_denied",
        )
        if denied is None:
            raise ConflictError("the invocation is no longer awaiting approval")
        await self._sync_message(tool=tool, invocation=denied)
        return denied

    async def attach_message(
        self,
        *,
        caller: AuthenticatedCaller,
        invocation_id: McpInvocationId,
        message_id: ChatMessageId,
    ) -> McpInvocationRecord:
        linked = await self._repository.link_message(
            org_id=caller.principal.org_id,
            invocation_id=invocation_id,
            user_id=caller.principal.principal_id,
            message_id=message_id,
        )
        if linked is None:
            raise NotFoundError("invocation or assistant message not found")
        return linked

    async def list_history(self, *, caller: AuthenticatedCaller) -> list[McpInvocationRecord]:
        records = await self._repository.list_invocations(
            org_id=caller.principal.org_id,
            user_id=caller.principal.principal_id,
        )
        return list(records)

    async def _authorize(
        self,
        *,
        caller: AuthenticatedCaller,
        tool: McpToolRecord,
        server: McpServerRecord,
        motivating_tier: TrustTier,
    ) -> tuple[McpGrantRecord | None, ToolAuthorizationDecision]:
        grant = await self._repository.get_grant(
            org_id=caller.principal.org_id,
            tool_id=tool.id,
            user_id=caller.principal.principal_id,
            at=self._clock.now(),
        )
        decision = authorize_tool_call(
            live_role_allows=caller.principal.has_permission(TOOL_INVOKE),
            has_active_grant=grant is not None,
            motivating_tier=motivating_tier,
            required_tier=server.min_trust_tier,
        )
        return grant, decision

    async def _validate_offending_source(
        self,
        *,
        caller: AuthenticatedCaller,
        decision: ToolAuthorizationDecision,
        offending_bundle_item_id: str | None,
    ) -> str | None:
        if decision.reason != TRUST_DENIED:
            return None
        if offending_bundle_item_id is None:
            raise ValidationError(
                "a trust-tier denial must identify its motivating bundle item",
                field="offending_bundle_item_id",
            )
        source = await self._repository.get_bundle_item_source(
            org_id=caller.principal.org_id,
            bundle_item_id=offending_bundle_item_id,
        )
        if source is None:
            raise ValidationError(
                "the offending bundle item is not available to this organisation",
                field="offending_bundle_item_id",
            )
        return source

    async def _owned_pending(
        self, *, caller: AuthenticatedCaller, invocation_id: McpInvocationId
    ) -> McpInvocationRecord:
        invocation = await self._repository.get_invocation(
            org_id=caller.principal.org_id, invocation_id=invocation_id
        )
        if invocation is None or invocation.user_id != caller.principal.principal_id:
            raise NotFoundError("invocation not found")
        if invocation.status is not InvocationStatus.PENDING_APPROVAL:
            raise ConflictError("the invocation is not awaiting approval")
        return invocation

    async def _load_tool_server(
        self, *, caller: AuthenticatedCaller, tool_id: McpToolId
    ) -> tuple[McpToolRecord, McpServerRecord]:
        tool = await self._repository.get_tool(org_id=caller.principal.org_id, tool_id=tool_id)
        if tool is None or not tool.is_enabled:
            raise NotFoundError("tool not found")
        server = await self._repository.get_server(
            org_id=caller.principal.org_id, server_id=tool.server_id
        )
        if server is None or not server.is_enabled:
            raise NotFoundError("tool server not found")
        return tool, server

    async def _dispatch(
        self,
        *,
        caller: AuthenticatedCaller,
        invocation: McpInvocationRecord,
        tool: McpToolRecord,
        server: McpServerRecord,
    ) -> McpInvocationRecord:
        credential_state = await self._repository.get_credential_state(
            org_id=caller.principal.org_id,
            server_id=server.id,
            user_id=caller.principal.principal_id,
        )
        if credential_state is not None and (
            credential_state.expires_at is not None
            and credential_state.expires_at <= self._clock.now()
        ):
            return await self._fail(invocation=invocation, tool=tool, code="credential_expired")
        stored = await self._repository.get_encrypted_credential(
            org_id=caller.principal.org_id,
            server_id=server.id,
            user_id=caller.principal.principal_id,
        )
        credential = (stored[0], self._cipher.decrypt(stored[1])) if stored is not None else None
        started = time.perf_counter()
        try:
            result = await self._client.call_tool(
                endpoint=server.endpoint,
                tool_name=tool.name,
                input_schema=tool.input_schema,
                arguments=invocation.arguments,
                credential=credential,
            )
        except Exception as exc:
            log.warning(
                "tool.invocation_failed",
                invocation_id=str(invocation.id),
                error_type=type(exc).__name__,
            )
            return await self._fail(
                invocation=invocation,
                tool=tool,
                code="tool_dispatch_failed",
                detail=type(exc).__name__,
            )
        duration_ms = int((time.perf_counter() - started) * 1_000)
        succeeded = await self._repository.transition_invocation(
            org_id=invocation.org_id,
            invocation_id=invocation.id,
            expected=InvocationStatus.APPROVED,
            status=InvocationStatus.SUCCEEDED,
            result=result,
            duration_ms=duration_ms,
        )
        if succeeded is None:
            raise ConflictError("the invocation changed while the tool was running")
        log.info(
            "tool.invocation_succeeded",
            invocation_id=str(invocation.id),
            duration_ms=duration_ms,
        )
        await self._sync_message(tool=tool, invocation=succeeded)
        return succeeded

    async def _fail(
        self,
        *,
        invocation: McpInvocationRecord,
        tool: McpToolRecord,
        code: str,
        detail: str | None = None,
    ) -> McpInvocationRecord:
        failed = await self._repository.transition_invocation(
            org_id=invocation.org_id,
            invocation_id=invocation.id,
            expected=InvocationStatus.APPROVED,
            status=InvocationStatus.FAILED,
            error_code=code,
            error_detail=detail,
        )
        if failed is None:
            raise ConflictError("the invocation changed while the tool was running")
        await self._sync_message(tool=tool, invocation=failed)
        return failed

    async def _sync_message(self, *, tool: McpToolRecord, invocation: McpInvocationRecord) -> None:
        if invocation.message_id is None:
            return
        await self._repository.update_linked_message(
            org_id=invocation.org_id,
            invocation_id=invocation.id,
            content=narrate_invocation(tool=tool, invocation=invocation),
        )


def narrate_invocation(*, tool: McpToolRecord, invocation: McpInvocationRecord) -> str:
    """Stable transcript copy for both the initial proposal and its terminal state."""
    if invocation.status is InvocationStatus.PENDING_APPROVAL:
        return f"I proposed `{tool.name}`. Review and approve it in Tools before it runs."
    if invocation.status is InvocationStatus.SUCCEEDED:
        structured = invocation.result.get("structuredContent")
        rendered = json.dumps(structured if structured is not None else invocation.result)
        return f"`{tool.name}` succeeded: {rendered}"
    if invocation.status is InvocationStatus.DENIED:
        source = (
            f" The motivating source was {invocation.offending_source}."
            if invocation.offending_source is not None
            else ""
        )
        return f"`{tool.name}` was denied ({invocation.denied_reason}).{source}"
    return f"`{tool.name}` failed ({invocation.error_code or 'unknown_error'})."
