"""The audit use case: record an event, list them back paginated.

Deliberately thin — no business logic beyond what the repository already
does. The one real decision this service embodies is what it does *not* do:
`record_event` runs in its own transaction, not the caller's. Coupling an
audit write to `features/memory`'s or `features/tools`' own commit would
require passing a shared session across a feature boundary those features do
not otherwise know about — the package layout rule ("`features` must never
import `flows`", and by the same logic never reach into a sibling feature's
persistence) does not support that. The residual risk — a crash in the
narrow window between the primary commit and this write loses exactly that
one audit row — is accepted at this scope (TRACKER §5 deliverable 5); a
system that needed two-phase-commit-grade audit durability is a different,
larger piece of work than this one."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from mnemos.core.errors import ValidationError
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.observability.application.ports import AuditRepository
from mnemos.features.observability.domain import (
    ActorKind,
    AuditEventPage,
    AuditEventRecord,
    AuditLogId,
    Outcome,
)

DEFAULT_PAGE_SIZE = 50


class AuditService:
    def __init__(self, *, repository: AuditRepository) -> None:
        self._repository = repository

    async def record_event(
        self,
        *,
        org_id: OrgId,
        actor_id: UserId | None,
        actor_kind: ActorKind,
        action: str,
        resource_kind: str,
        resource_id: str | None = None,
        outcome: Outcome,
        reason: str | None = None,
        request_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEventRecord:
        return await self._repository.record(
            org_id=org_id,
            actor_id=actor_id,
            actor_kind=actor_kind,
            action=action,
            resource_kind=resource_kind,
            resource_id=resource_id,
            outcome=outcome,
            reason=reason,
            request_id=request_id,
            detail=detail,
        )

    async def list_events(
        self,
        *,
        org_id: OrgId,
        actor_id: UserId | None = None,
        action: str | None = None,
        resource_kind: str | None = None,
        outcome: Outcome | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> AuditEventPage:
        before = decode_cursor(cursor) if cursor is not None else None
        rows = await self._repository.list_events(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            resource_kind=resource_kind,
            outcome=outcome,
            since=since,
            until=until,
            limit=limit + 1,
            before=before,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1]) if has_more and page else None
        return AuditEventPage(events=tuple(page), next_cursor=next_cursor)


def encode_cursor(event: AuditEventRecord) -> str:
    return f"{event.occurred_at.isoformat()}|{event.id}"


def decode_cursor(cursor: str) -> tuple[datetime, AuditLogId]:
    timestamp, _, raw_id = cursor.rpartition("|")
    if not timestamp or not raw_id:
        raise ValidationError("malformed pagination cursor", field="cursor")
    try:
        return datetime.fromisoformat(timestamp), AuditLogId(uuid.UUID(raw_id))
    except ValueError as exc:
        raise ValidationError("malformed pagination cursor", field="cursor") from exc
