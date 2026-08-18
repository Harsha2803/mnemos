"""Immutable records for bitemporal memory and its lineage graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NewType
from uuid import UUID

from mnemos.core.types import EdgeKind, MemoryKind, MemoryStatus, TrustTier
from mnemos.features.identity.domain import OrgId, UserId

SubjectId = NewType("SubjectId", UUID)
MemoryId = NewType("MemoryId", UUID)


@dataclass(frozen=True, slots=True)
class SubjectRecord:
    id: SubjectId
    org_id: OrgId
    kind: str
    external_ref: str
    display_name: str
    attributes: dict[str, str]


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: MemoryId
    org_id: OrgId
    subject: SubjectRecord
    predicate: str
    object_text: str
    kind: MemoryKind
    status: MemoryStatus
    scope: dict[str, str]
    valid_from: datetime
    valid_to: datetime
    recorded_at: datetime
    retracted_at: datetime | None
    confidence: float
    trust_tier: TrustTier
    source_kind: str
    source_ref: str | None
    created_by: UserId | None


@dataclass(frozen=True, slots=True)
class MemoryEdgeRecord:
    id: UUID
    source_id: MemoryId
    target_id: MemoryId
    kind: EdgeKind
    rationale: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryHistory:
    claims: tuple[MemoryRecord, ...]
    edges: tuple[MemoryEdgeRecord, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class MemoryWriteResult:
    claim: MemoryRecord
    superseded: tuple[MemoryId, ...]
