"""Audit log route: `GET /audit/events`.

Authenticated by doing nothing (same as every other router), but gated by a
real permission on top of that — `audit:read`, held only by `admin`'s `*:*`
wildcard (`features/identity/domain/roles.py`). A non-admin caller gets a
real 403, not a hidden route: the same "watch a user without the permission
be refused" claim `C1`'s deferred description names, landing here because
this is the first place in the product a non-admin-gated route actually
exists (TRACKER §5 deliverable 5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from mnemos.core.errors import AuthorizationError
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.features.identity.domain import Permission, UserId
from mnemos.features.observability.application.service import AuditService
from mnemos.features.observability.domain import AuditEventRecord

router = APIRouter(prefix="/audit", tags=["audit"])

MAX_LIMIT = 200
DEFAULT_LIMIT = 50

_AUDIT_READ = Permission.require("audit", "read")


class AuditEventResponse(BaseModel):
    id: str
    actor_id: str | None
    actor_kind: Literal["user", "api_key", "system"]
    action: str
    resource_kind: str
    resource_id: str | None
    outcome: Literal["allow", "deny"]
    reason: str | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    occurred_at: str


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse]
    next_cursor: str | None


def _event_response(record: AuditEventRecord) -> AuditEventResponse:
    return AuditEventResponse(
        id=str(record.id),
        actor_id=str(record.actor_id) if record.actor_id is not None else None,
        actor_kind=record.actor_kind,
        action=record.action,
        resource_kind=record.resource_kind,
        resource_id=record.resource_id,
        outcome=record.outcome,
        reason=record.reason,
        request_id=record.request_id,
        ip_address=record.ip_address,
        user_agent=record.user_agent,
        occurred_at=record.occurred_at.isoformat(),
    )


def _service(request: Request) -> AuditService:
    service = getattr(request.app.state, "audit_service", None)
    if not isinstance(service, AuditService):  # pragma: no cover - the lifespan sets it
        msg = "audit service is not configured"
        raise RuntimeError(msg)
    return service


@router.get("/events")
async def list_events(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[AuditService, Depends(_service)],
    actor_id: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource_kind: Annotated[str | None, Query(max_length=64)] = None,
    outcome: Annotated[Literal["allow", "deny"] | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> AuditEventListResponse:
    if not caller.principal.has_permission(_AUDIT_READ):
        raise AuthorizationError("only administrators can view the audit log")
    page = await service.list_events(
        org_id=caller.principal.org_id,
        actor_id=UserId(uuid.UUID(actor_id)) if actor_id is not None else None,
        action=action,
        resource_kind=resource_kind,
        outcome=outcome,
        since=since,
        until=until,
        limit=limit,
        cursor=cursor,
    )
    return AuditEventListResponse(
        events=[_event_response(event) for event in page.events],
        next_cursor=page.next_cursor,
    )
