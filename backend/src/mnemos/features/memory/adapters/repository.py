"""Postgres repository for immutable bitemporal claims.

Fact arbitration locks the logical key, retracts every overlapping live belief,
inserts the replacement, and writes its lineage edge in one transaction. The
database exclusion constraint and cycle trigger remain the final authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import or_, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.ranges import Range

from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.core.ids import IdGenerator
from mnemos.core.types import EdgeKind, MemoryKind, MemoryStatus, TrustTier
from mnemos.features.identity.adapters.models import Tag
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.memory.adapters.models import Memory, MemoryEdge, MemoryEmbedding, Subject
from mnemos.features.memory.domain import (
    MemoryEdgeRecord,
    MemoryHistory,
    MemoryId,
    MemoryRecord,
    MemoryWriteResult,
    SubjectId,
    SubjectRecord,
)
from mnemos.platform.db import Database


def scope_digest(scope: dict[str, str]) -> str:
    canonical = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class SqlMemoryRepository:
    """`MemoryRepository` over the already-migrated memory tables."""

    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def write(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        subject_kind: str,
        subject_ref: str,
        subject_name: str,
        predicate: str,
        object_text: str,
        kind: MemoryKind,
        scope: dict[str, str],
        valid_from: datetime,
        valid_to: datetime,
        confidence: float,
        trust_tier: TrustTier,
        source_kind: str,
        source_ref: str | None,
        recorded_at: datetime,
        supersede_id: MemoryId | None = None,
    ) -> MemoryWriteResult:
        digest = scope_digest(scope)
        new_id = self._ids.new()
        edge_ids: list[MemoryId] = []

        async with self._db.session(org_id=org_id) as session:
            subject_id = await session.scalar(
                insert(Subject)
                .values(
                    id=self._ids.new(),
                    org_id=org_id,
                    kind=subject_kind,
                    external_ref=subject_ref,
                    display_name=subject_name,
                    attributes={},
                )
                .on_conflict_do_update(
                    constraint="uq_subject_org_id_kind_external_ref",
                    set_={"display_name": subject_name},
                )
                .returning(Subject.id)
            )
            if subject_id is None:  # pragma: no cover - RETURNING is total
                raise RuntimeError("subject upsert returned no id")

            overlapping: Sequence[Memory] = ()
            if kind is MemoryKind.FACT:
                overlapping = (
                    await session.scalars(
                        select(Memory)
                        .where(
                            Memory.org_id == org_id,
                            Memory.subject_id == subject_id,
                            Memory.predicate == predicate,
                            Memory.scope_hash == digest,
                            Memory.kind == MemoryKind.FACT.value,
                            Memory.retracted_at.is_(None),
                            Memory.valid_range.op("&&")(Range(valid_from, valid_to, bounds="[)")),
                        )
                        .with_for_update()
                    )
                ).all()

            if supersede_id is not None and all(row.id != supersede_id for row in overlapping):
                exists = await session.scalar(
                    select(Memory.id).where(
                        Memory.org_id == org_id,
                        Memory.id == supersede_id,
                        Memory.retracted_at.is_(None),
                    )
                )
                if exists is None:
                    raise NotFoundError(f"memory {supersede_id} not found")
                raise ValidationError(
                    "the replacement must preserve subject, predicate, scope, and overlap",
                    field="memory_id",
                )

            for prior in overlapping:
                prior.status = MemoryStatus.SUPERSEDED.value
                # `recorded_at` is server-owned; using `now()` here gives every
                # row in this transaction the identical belief-time boundary.
                await session.execute(
                    update(Memory)
                    .where(Memory.org_id == org_id, Memory.id == prior.id)
                    .values(retracted_at=recorded_at)
                )
                await session.execute(
                    update(MemoryEmbedding)
                    .where(
                        MemoryEmbedding.org_id == org_id,
                        MemoryEmbedding.memory_id == prior.id,
                    )
                    .values(is_live=False)
                )
                edge_ids.append(MemoryId(prior.id))

            row = Memory(
                id=new_id,
                org_id=org_id,
                subject_id=subject_id,
                predicate=predicate,
                object_text=object_text,
                object_json={},
                kind=kind.value,
                status=MemoryStatus.ACTIVE.value,
                scope=scope,
                scope_hash=digest,
                valid_range=Range(valid_from, valid_to, bounds="[)"),
                confidence=confidence,
                trust_tier=int(trust_tier),
                source_kind=source_kind,
                source_ref=source_ref,
                created_by=user_id,
            )
            row.recorded_at = recorded_at
            session.add(row)
            await session.flush()

            for prior_id in edge_ids:
                session.add(
                    MemoryEdge(
                        id=self._ids.new(),
                        org_id=org_id,
                        src_id=new_id,
                        dst_id=prior_id,
                        kind=EdgeKind.SUPERSEDES.value,
                        rationale="new overlapping fact superseded the prior live belief",
                    )
                )
            await session.flush()
            await session.refresh(row)
            subject = await session.get(Subject, subject_id)
            if subject is None:  # pragma: no cover - FK and same transaction
                raise RuntimeError("subject vanished during memory write")
            record = _memory_record(row, subject)

        return MemoryWriteResult(claim=record, superseded=tuple(edge_ids))

    async def retract(self, *, org_id: OrgId, memory_id: MemoryId, at: datetime) -> bool:
        async with self._db.session(org_id=org_id) as session:
            changed = await session.scalar(
                update(Memory)
                .where(
                    Memory.org_id == org_id,
                    Memory.id == memory_id,
                    Memory.retracted_at.is_(None),
                )
                .values(retracted_at=at, status=MemoryStatus.RETRACTED.value)
                .returning(Memory.id)
            )
            if changed is not None:
                await session.execute(
                    update(MemoryEmbedding)
                    .where(
                        MemoryEmbedding.org_id == org_id,
                        MemoryEmbedding.memory_id == memory_id,
                    )
                    .values(is_live=False)
                )
        return changed is not None

    async def history(
        self,
        *,
        org_id: OrgId,
        caller_tags: Sequence[str],
        subject_ref: str | None,
        as_of: datetime | None,
        believed_at: datetime | None,
        include_retracted: bool,
    ) -> MemoryHistory:
        async with self._db.session(org_id=org_id) as session:
            tag_ids = list(
                await session.scalars(
                    select(Tag.id).where(Tag.org_id == org_id, Tag.slug.in_(caller_tags))
                )
            )
            public = Memory.acl_tag_ids == []
            acl = (
                or_(
                    public,
                    Memory.acl_tag_ids.overlap(
                        postgresql.array(tag_ids, type_=postgresql.UUID(as_uuid=True))
                    ),
                )
                if tag_ids
                else public
            )
            query = (
                select(Memory, Subject)
                .join(Subject, Subject.id == Memory.subject_id)
                .where(Memory.org_id == org_id, Subject.org_id == org_id, acl)
                .order_by(Memory.recorded_at.desc(), Memory.id.desc())
            )
            if subject_ref is not None:
                query = query.where(Subject.external_ref == subject_ref)
            if as_of is not None:
                query = query.where(Memory.valid_range.op("@>")(as_of))
            if believed_at is not None:
                query = query.where(
                    Memory.recorded_at <= believed_at,
                    or_(Memory.retracted_at.is_(None), Memory.retracted_at > believed_at),
                )
            elif not include_retracted:
                query = query.where(Memory.retracted_at.is_(None))
            rows = (await session.execute(query)).all()
            claim_ids = [row.Memory.id for row in rows]
            edges: Sequence[MemoryEdge] = ()
            if claim_ids:
                edges = (
                    await session.scalars(
                        select(MemoryEdge)
                        .where(
                            MemoryEdge.org_id == org_id,
                            or_(
                                MemoryEdge.src_id.in_(claim_ids),
                                MemoryEdge.dst_id.in_(claim_ids),
                            ),
                        )
                        .order_by(MemoryEdge.created_at.asc(), MemoryEdge.id.asc())
                    )
                ).all()

        return MemoryHistory(
            claims=tuple(_memory_record(row.Memory, row.Subject) for row in rows),
            edges=tuple(_edge_record(edge) for edge in edges),
        )


def _memory_record(row: Memory, subject: Subject) -> MemoryRecord:
    validity = cast(Range[datetime], row.valid_range)
    if validity.lower is None or validity.upper is None:  # pragma: no cover - service forbids it
        raise RuntimeError("memory validity must be bounded")
    return MemoryRecord(
        id=MemoryId(row.id),
        org_id=OrgId(row.org_id),
        subject=SubjectRecord(
            id=SubjectId(subject.id),
            org_id=OrgId(subject.org_id),
            kind=subject.kind,
            external_ref=subject.external_ref,
            display_name=subject.display_name,
            attributes={str(k): str(v) for k, v in subject.attributes.items()},
        ),
        predicate=row.predicate,
        object_text=row.object_text,
        kind=MemoryKind(row.kind),
        status=MemoryStatus(row.status),
        scope={str(k): str(v) for k, v in row.scope.items()},
        valid_from=validity.lower,
        valid_to=validity.upper,
        recorded_at=row.recorded_at,
        retracted_at=row.retracted_at,
        confidence=row.confidence,
        trust_tier=TrustTier(row.trust_tier),
        source_kind=row.source_kind,
        source_ref=row.source_ref,
        created_by=UserId(row.created_by) if row.created_by is not None else None,
    )


def _edge_record(row: MemoryEdge) -> MemoryEdgeRecord:
    return MemoryEdgeRecord(
        id=row.id,
        source_id=MemoryId(row.src_id),
        target_id=MemoryId(row.dst_id),
        kind=EdgeKind(row.kind),
        rationale=row.rationale,
        created_at=row.created_at,
    )
