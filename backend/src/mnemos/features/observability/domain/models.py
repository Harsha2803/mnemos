"""Pure record for one audit event. Flat value object, not an ORM row
(CodingStandards §6) — see `chat/domain/models.py` for why."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.observability.domain.ids import AuditLogId

ActorKind = Literal["user", "api_key", "system"]
Outcome = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    id: AuditLogId
    org_id: OrgId
    actor_id: UserId | None
    actor_kind: ActorKind
    action: str
    resource_kind: str
    resource_id: str | None
    outcome: Outcome
    reason: str | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    detail: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEventPage:
    events: tuple[AuditEventRecord, ...]
    next_cursor: str | None
