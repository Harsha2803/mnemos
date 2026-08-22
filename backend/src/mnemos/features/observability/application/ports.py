"""What `AuditService` needs from persistence, named as a `Protocol` so the
service can be tested against an in-memory fake and the adapter stays
swappable (CodingStandards §5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.observability.domain import ActorKind, AuditEventRecord, AuditLogId, Outcome


class AuditRepository(Protocol):
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
    ) -> AuditEventRecord: ...

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
        """Newest first by `(occurred_at, id)` — the explicit `id` tiebreak
        every new list query in this milestone uses."""
        ...
