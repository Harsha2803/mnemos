"""`AuditRepository` over Postgres.

Every statement runs inside `Database.session(org_id=...)`, so `app.current_org`
is bound for the transaction and row-level security applies underneath the
explicit `org_id` predicate — the same discipline every other repository in
this codebase follows (see `chat/adapters/repository.py`'s docstring).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import literal, select, tuple_

from mnemos.core.ids import IdGenerator
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.observability.adapters.models import AuditLog
from mnemos.features.observability.domain import (
    ActorKind,
    AuditEventRecord,
    AuditLogId,
    Outcome,
)
from mnemos.platform.db import Database


class SqlAuditRepository:
    """`AuditRepository` over Postgres."""

    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def record(
        self,
        *,
        org_id: OrgId,
        actor_id: UserId | None,
        actor_kind: ActorKind,
        action: str,
        resource_kind: str,
        resource_id: str | None,
        outcome: Outcome,
        reason: str | None = None,
        request_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEventRecord:
        new_id = self._ids.new()
        async with self._db.session(org_id=org_id) as session:
            row = AuditLog(
                id=new_id,
                org_id=org_id,
                actor_id=actor_id,
                actor_kind=actor_kind,
                action=action,
                resource_kind=resource_kind,
                resource_id=resource_id,
                outcome=outcome,
                reason=reason,
                request_id=request_id,
                detail=detail or {},
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _audit_record(row)

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
        limit: int,
        before: tuple[datetime, AuditLogId] | None = None,
    ) -> Sequence[AuditEventRecord]:
        query = select(AuditLog).where(AuditLog.org_id == org_id)
        if actor_id is not None:
            query = query.where(AuditLog.actor_id == actor_id)
        if action is not None:
            query = query.where(AuditLog.action == action)
        if resource_kind is not None:
            query = query.where(AuditLog.resource_kind == resource_kind)
        if outcome is not None:
            query = query.where(AuditLog.outcome == outcome)
        if since is not None:
            query = query.where(AuditLog.occurred_at >= since)
        if until is not None:
            query = query.where(AuditLog.occurred_at <= until)
        query = query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit)
        if before is not None:
            before_ts, before_id = before
            query = query.where(
                tuple_(AuditLog.occurred_at, AuditLog.id)
                < tuple_(literal(before_ts), literal(before_id))
            )
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.scalars(query)).all()
        return [_audit_record(r) for r in rows]


def _audit_record(row: AuditLog) -> AuditEventRecord:
    return AuditEventRecord(
        id=AuditLogId(row.id),
        org_id=OrgId(row.org_id),
        actor_id=UserId(row.actor_id) if row.actor_id is not None else None,
        actor_kind=row.actor_kind,  # type: ignore[arg-type]
        action=row.action,
        resource_kind=row.resource_kind,
        resource_id=row.resource_id,
        outcome=row.outcome,  # type: ignore[arg-type]
        reason=row.reason,
        request_id=row.request_id,
        ip_address=str(row.ip_address) if row.ip_address is not None else None,
        user_agent=row.user_agent,
        detail=row.detail,
        occurred_at=row.occurred_at,
    )
