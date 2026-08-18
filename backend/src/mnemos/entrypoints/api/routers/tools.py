"""Authenticated MCP registry, approval, invocation, and history endpoints."""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from mnemos.core.errors import AuthorizationError, NotFoundError, ValidationError
from mnemos.core.types import JsonValue, TrustTier
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.features.identity.domain import Permission
from mnemos.features.tools.application import ToolCatalogService, ToolInvocationService
from mnemos.features.tools.domain import (
    McpGrantRecord,
    McpInvocationId,
    McpInvocationRecord,
    McpServerId,
    McpServerRecord,
    McpToolId,
    McpToolRecord,
)

router = APIRouter(prefix="/tools", tags=["tools"])

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOOL_MANAGE = Permission.require("tool", "manage")
_TOOL_INVOKE = Permission.require("tool", "invoke")


class RegisterServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1_000)
    endpoint: str = Field(min_length=1, max_length=2_000)
    min_trust_tier: TrustTier = TrustTier.USER
    requires_approval: bool = True


class SaveCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme: Literal["none", "bearer", "api_key"]
    secret: SecretStr = Field(default=SecretStr(""), max_length=8_192)


class GrantSelfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_approve: bool = False


class ProposeInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    arguments: dict[str, object]
    # The client may only lower authority by supplying a real, org-visible
    # bundle item. It cannot submit a numeric trust tier and claim SYSTEM.
    offending_bundle_item_id: str | None = None


class ServerResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    endpoint: str
    min_trust_tier: int
    requires_approval: bool
    last_discovered_at: str | None
    health_status: str | None
    credential_configured: bool


class ToolResponse(BaseModel):
    id: str
    server_id: str
    name: str
    description: str | None
    input_schema: dict[str, object]
    requires_approval: bool
    is_mutating: bool


class GrantResponse(BaseModel):
    id: str
    tool_id: str
    user_id: str
    auto_approve: bool
    expires_at: str | None


class InvocationResponse(BaseModel):
    id: str
    tool_id: str
    user_id: str
    arguments: dict[str, object]
    status: str
    caller_trust_tier: int
    denied_reason: str | None
    offending_source: str | None
    approved_by: str | None
    approved_at: str | None
    result: dict[str, object]
    duration_ms: int | None
    error_code: str | None
    created_at: str


def _catalog(request: Request) -> ToolCatalogService:
    service = getattr(request.app.state, "tool_catalog", None)
    if not isinstance(service, ToolCatalogService):  # pragma: no cover - lifespan owns this
        raise RuntimeError("the tool catalog is not configured")
    return service


def _invocations(request: Request) -> ToolInvocationService:
    service = getattr(request.app.state, "tool_invocations", None)
    if not isinstance(service, ToolInvocationService):  # pragma: no cover
        raise RuntimeError("tool invocations are not configured")
    return service


@router.post("/servers", status_code=status.HTTP_201_CREATED)
async def register_server(
    body: RegisterServerRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    catalog: Annotated[ToolCatalogService, Depends(_catalog)],
) -> ServerResponse:
    _require(caller, _TOOL_MANAGE)
    if _SLUG.fullmatch(body.slug) is None:
        raise ValidationError("slug must be lowercase kebab-case", field="slug")
    record = await catalog.register_server(
        org_id=caller.principal.org_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        endpoint=body.endpoint,
        min_trust_tier=body.min_trust_tier,
        requires_approval=body.requires_approval,
    )
    return _server_response(record, credential_configured=False)


@router.get("/servers")
async def list_servers(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    catalog: Annotated[ToolCatalogService, Depends(_catalog)],
) -> list[ServerResponse]:
    _require_any_tool_access(caller)
    records = await catalog.list_servers(org_id=caller.principal.org_id)
    result: list[ServerResponse] = []
    for record in records:
        credential = await catalog.credential_state(
            org_id=caller.principal.org_id,
            user_id=caller.principal.principal_id,
            server_id=record.id,
        )
        result.append(_server_response(record, credential_configured=credential is not None))
    return result


@router.put("/servers/{server_id}/credential", status_code=status.HTTP_204_NO_CONTENT)
async def save_credential(
    server_id: str,
    body: SaveCredentialRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    catalog: Annotated[ToolCatalogService, Depends(_catalog)],
) -> None:
    _require_any_tool_access(caller)
    await catalog.save_credential(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        server_id=_server_id(server_id),
        scheme=body.scheme,
        secret=body.secret.get_secret_value(),
    )


@router.post("/servers/{server_id}/discover")
async def discover_tools(
    server_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    catalog: Annotated[ToolCatalogService, Depends(_catalog)],
) -> list[ToolResponse]:
    _require(caller, _TOOL_MANAGE)
    records = await catalog.discover(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        server_id=_server_id(server_id),
    )
    return [_tool_response(record) for record in records]


@router.get("")
async def list_tools(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    catalog: Annotated[ToolCatalogService, Depends(_catalog)],
) -> list[ToolResponse]:
    _require_any_tool_access(caller)
    return [
        _tool_response(record)
        for record in await catalog.list_tools(org_id=caller.principal.org_id)
    ]


@router.post("/{tool_id}/grants/self")
async def grant_tool_to_self(
    tool_id: str,
    body: GrantSelfRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    invocations: Annotated[ToolInvocationService, Depends(_invocations)],
) -> GrantResponse:
    record = await invocations.grant_to_self(
        caller=caller, tool_id=_tool_id(tool_id), auto_approve=body.auto_approve
    )
    return _grant_response(record)


@router.post("/invocations", status_code=status.HTTP_201_CREATED)
async def propose_invocation(
    body: ProposeInvocationRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    invocations: Annotated[ToolInvocationService, Depends(_invocations)],
) -> InvocationResponse:
    motivating_tier = (
        TrustTier.RETRIEVED
        if body.offending_bundle_item_id is not None
        else TrustTier.USER
    )
    record = await invocations.propose(
        caller=caller,
        tool_id=_tool_id(body.tool_id),
        arguments=cast(dict[str, JsonValue], body.arguments),
        motivating_tier=motivating_tier,
        offending_bundle_item_id=body.offending_bundle_item_id,
    )
    return _invocation_response(record)


@router.get("/invocations")
async def list_invocations(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    invocations: Annotated[ToolInvocationService, Depends(_invocations)],
) -> list[InvocationResponse]:
    _require_any_tool_access(caller)
    return [
        _invocation_response(record)
        for record in await invocations.list_history(caller=caller)
    ]


@router.post("/invocations/{invocation_id}/approve")
async def approve_invocation(
    invocation_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    invocations: Annotated[ToolInvocationService, Depends(_invocations)],
) -> InvocationResponse:
    return _invocation_response(
        await invocations.approve(
            caller=caller, invocation_id=_invocation_id(invocation_id)
        )
    )


@router.post("/invocations/{invocation_id}/deny")
async def deny_invocation(
    invocation_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    invocations: Annotated[ToolInvocationService, Depends(_invocations)],
) -> InvocationResponse:
    return _invocation_response(
        await invocations.deny(caller=caller, invocation_id=_invocation_id(invocation_id))
    )


def _require(caller: AuthenticatedCaller, permission: Permission) -> None:
    if not caller.principal.has_permission(permission):
        raise AuthorizationError("you are not allowed to perform this tool operation")


def _require_any_tool_access(caller: AuthenticatedCaller) -> None:
    if not (
        caller.principal.has_permission(_TOOL_INVOKE)
        or caller.principal.has_permission(_TOOL_MANAGE)
    ):
        raise AuthorizationError("you are not allowed to access tools")


def _server_response(record: McpServerRecord, *, credential_configured: bool) -> ServerResponse:
    return ServerResponse(
        id=str(record.id),
        slug=record.slug,
        name=record.name,
        description=record.description,
        endpoint=record.endpoint,
        min_trust_tier=int(record.min_trust_tier),
        requires_approval=record.requires_approval,
        last_discovered_at=(
            record.last_discovered_at.isoformat()
            if record.last_discovered_at is not None
            else None
        ),
        health_status=record.health_status,
        credential_configured=credential_configured,
    )


def _tool_response(record: McpToolRecord) -> ToolResponse:
    return ToolResponse(
        id=str(record.id),
        server_id=str(record.server_id),
        name=record.name,
        description=record.description,
        input_schema=cast(dict[str, object], record.input_schema),
        requires_approval=record.requires_approval,
        is_mutating=record.is_mutating,
    )


def _grant_response(record: McpGrantRecord) -> GrantResponse:
    return GrantResponse(
        id=str(record.id),
        tool_id=str(record.tool_id),
        user_id=str(record.user_id),
        auto_approve=record.auto_approve,
        expires_at=record.expires_at.isoformat() if record.expires_at is not None else None,
    )


def _invocation_response(record: McpInvocationRecord) -> InvocationResponse:
    return InvocationResponse(
        id=str(record.id),
        tool_id=str(record.tool_id),
        user_id=str(record.user_id),
        arguments=cast(dict[str, object], record.arguments),
        status=record.status.value,
        caller_trust_tier=int(record.caller_trust_tier),
        denied_reason=record.denied_reason,
        offending_source=record.offending_source,
        approved_by=str(record.approved_by) if record.approved_by is not None else None,
        approved_at=record.approved_at.isoformat() if record.approved_at is not None else None,
        result=cast(dict[str, object], record.result),
        duration_ms=record.duration_ms,
        error_code=record.error_code,
        created_at=record.created_at.isoformat(),
    )


def _server_id(raw: str) -> McpServerId:
    try:
        return McpServerId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError("tool server not found") from exc


def _tool_id(raw: str) -> McpToolId:
    try:
        return McpToolId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError("tool not found") from exc


def _invocation_id(raw: str) -> McpInvocationId:
    try:
        return McpInvocationId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError("invocation not found") from exc
