"""`IngestJobRepository`: the worker's claim/complete protocol over `ingest_job`
(`B1` deliverable 4).

**`claim_next` is the second caller `platform/db.py`'s `elevated_session`
reserves** (the first is bootstrap, `bootstrap_store.py`). A worker claims
across every org's queue in one poll — it does not yet know which org's job
it will get — so there is no `org_id` to scope a session to until after the
claim returns one. That is genuinely different from every other query in
this codebase, which is why it is the one place this repository escapes row-
level security rather than filtering by it.

Once a job is claimed, its `org_id` is known, and every subsequent write
(`mark_succeeded`/`mark_failed`) goes back through the ordinary `db.session
(org_id=...)` — RLS as defense in depth, same discipline every other
repository follows (CodingStandards §6). Escaping isolation is a claim-time
necessity, not a standing exemption for this repository.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mnemos.core.clock import SYSTEM_CLOCK
from mnemos.core.errors import ConflictError
from mnemos.core.ids import IdGenerator
from mnemos.features.identity.domain import OrgId
from mnemos.features.knowledge.adapters.models import IngestJob
from mnemos.features.knowledge.domain import (
    ClaimedIngestJob,
    DocumentId,
    IngestJobEventRecord,
    IngestJobRecord,
    JobId,
)
from mnemos.platform.db import Database


class IngestJobRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def enqueue(
        self,
        *,
        org_id: OrgId,
        kind: str,
        payload: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> JobId:
        """The ORM's own `JSONB` type handles serialization — raw SQL would
        need an explicit `::jsonb` cast, since a `str` bound parameter has no
        implicit cast to `jsonb` the way an unknown-typed literal does."""
        new_id = self._ids.new()
        try:
            async with self._db.session(org_id=org_id) as session:
                session.add(
                    IngestJob(
                        id=new_id,
                        org_id=org_id,
                        kind=kind,
                        status="queued",
                        payload=dict(payload),
                        idempotency_key=idempotency_key,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "an ingest job for this item already exists", idempotency_key=idempotency_key
            ) from exc
        return JobId(new_id)

    async def list_recent(self, *, org_id: OrgId, limit: int = 50) -> list[IngestJobRecord]:
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, org_id, kind, status, payload, document_id, attempts, max_attempts,
                           total_units, done_units, owner_id, heartbeat_at, lease_expires_at,
                           started_at, finished_at, error_code, error_detail, created_at, updated_at
                      FROM ingest_job
                     WHERE org_id = :org_id
                     ORDER BY updated_at DESC, created_at DESC
                     LIMIT :limit
                    """
                ),
                {"org_id": org_id, "limit": limit},
            )
            rows = list(result.mappings())
            events = await self._events_for_jobs(
                session=session, org_id=org_id, job_ids=[JobId(row["id"]) for row in rows]
            )

        return [self._record(row, events.get(JobId(row["id"]), ())) for row in rows]

    async def get_for_org(self, *, org_id: OrgId, job_id: JobId) -> IngestJobRecord | None:
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, org_id, kind, status, payload, document_id, attempts, max_attempts,
                           total_units, done_units, owner_id, heartbeat_at, lease_expires_at,
                           started_at, finished_at, error_code, error_detail, created_at, updated_at
                      FROM ingest_job
                     WHERE org_id = :org_id AND id = :job_id
                    """
                ),
                {"org_id": org_id, "job_id": job_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            events = await self._events_for_jobs(session=session, org_id=org_id, job_ids=[job_id])

        return self._record(row, events.get(job_id, ()))

    async def claim_next(self, *, owner_id: str, lease_seconds: int) -> ClaimedIngestJob | None:
        """Oldest `queued` job first, `FOR UPDATE SKIP LOCKED` so two worker
        replicas polling at once never claim the same row — the same
        concurrency shape `reap_stuck_jobs` already uses."""
        now = SYSTEM_CLOCK.now()
        lease_expires = now + timedelta(seconds=lease_seconds)
        async with self._db.elevated_session() as session:
            result = await session.execute(
                text(
                    """
                    WITH next_job AS (
                        SELECT id FROM ingest_job
                         WHERE status = 'queued'
                           AND (lease_expires_at IS NULL OR lease_expires_at <= :now)
                         ORDER BY created_at
                         FOR UPDATE SKIP LOCKED
                         LIMIT 1
                    )
                    UPDATE ingest_job j
                       SET status = 'running',
                           owner_id = :owner_id,
                           heartbeat_at = :now,
                           lease_expires_at = :lease_expires,
                           started_at = COALESCE(j.started_at, :now),
                           finished_at = NULL,
                           error_code = NULL,
                           error_detail = NULL,
                           done_units = 0,
                           total_units = 0,
                           updated_at = :now,
                           attempts = j.attempts + 1
                      FROM next_job n
                     WHERE j.id = n.id
                 RETURNING j.id, j.org_id, j.kind, j.payload, j.document_id,
                           j.attempts, j.max_attempts
                    """
                ),
                {"owner_id": owner_id, "now": now, "lease_expires": lease_expires},
            )
            row = result.mappings().first()
            if row is None:
                return None

            await session.execute(
                text(
                    """
                    INSERT INTO ingest_job_event (org_id, job_id, from_status, to_status, owner_id, detail)
                    VALUES (:org_id, :job_id, 'queued', 'running', :owner_id, 'claimed by worker')
                    """
                ),
                {"org_id": row["org_id"], "job_id": row["id"], "owner_id": owner_id},
            )

        raw_payload = row["payload"]
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
        return ClaimedIngestJob(
            id=JobId(row["id"]),
            org_id=OrgId(row["org_id"]),
            kind=row["kind"],
            payload=payload,
            document_id=DocumentId(row["document_id"]) if row["document_id"] else None,
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
        )

    async def heartbeat(
        self, *, job_id: JobId, org_id: OrgId, owner_id: str, lease_seconds: int
    ) -> bool:
        now = SYSTEM_CLOCK.now()
        lease_expires = now + timedelta(seconds=lease_seconds)
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE ingest_job
                       SET heartbeat_at = :now, lease_expires_at = :lease_expires,
                           updated_at = :now
                     WHERE id = :id AND status = 'running' AND owner_id = :owner_id
                 RETURNING id
                    """
                ),
                {
                    "id": job_id,
                    "owner_id": owner_id,
                    "now": now,
                    "lease_expires": lease_expires,
                },
            )
        return result.first() is not None

    async def record_progress(
        self,
        *,
        job_id: JobId,
        org_id: OrgId,
        owner_id: str,
        done_units: int,
        total_units: int,
        detail: str | None = None,
    ) -> bool:
        total_units = max(0, total_units)
        done_units = min(max(0, done_units), total_units)
        now = SYSTEM_CLOCK.now()
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE ingest_job
                       SET done_units = :done_units, total_units = :total_units,
                           updated_at = :now
                     WHERE id = :id AND status = 'running' AND owner_id = :owner_id
                 RETURNING id
                    """
                ),
                {
                    "id": job_id,
                    "owner_id": owner_id,
                    "done_units": done_units,
                    "total_units": total_units,
                    "now": now,
                },
            )
            if result.first() is None:
                return False
            if detail is not None:
                await session.execute(
                    text(
                        """
                        INSERT INTO ingest_job_event (
                            org_id, job_id, from_status, to_status, owner_id, detail
                        )
                        VALUES (:org_id, :job_id, 'running', 'running', :owner_id, :detail)
                        """
                    ),
                    {
                        "org_id": org_id,
                        "job_id": job_id,
                        "owner_id": owner_id,
                        "detail": detail,
                    },
                )
        return True

    async def mark_succeeded(
        self, *, job_id: JobId, org_id: OrgId, owner_id: str, document_id: DocumentId
    ) -> bool:
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE ingest_job
                       SET status = 'succeeded', document_id = :document_id,
                           finished_at = :now, owner_id = NULL, heartbeat_at = NULL,
                           lease_expires_at = NULL, error_code = NULL, error_detail = NULL,
                           updated_at = :now
                     WHERE id = :id AND status = 'running' AND owner_id = :owner_id
                 RETURNING id
                    """
                ),
                {
                    "id": job_id,
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "now": SYSTEM_CLOCK.now(),
                },
            )
            if result.first() is None:
                return False
            await session.execute(
                text(
                    """
                    INSERT INTO ingest_job_event (
                        org_id, job_id, from_status, to_status, owner_id, detail
                    )
                    VALUES (:org_id, :job_id, 'running', 'succeeded', :owner_id, 'ingested')
                    """
                ),
                {"org_id": org_id, "job_id": job_id, "owner_id": owner_id},
            )
        return True

    async def mark_attempt_failed(
        self,
        *,
        job_id: JobId,
        org_id: OrgId,
        owner_id: str,
        error_code: str,
        error_detail: str,
    ) -> str | None:
        """Record a failed attempt. Return the job's next status: `queued` for
        retry, `failed` once `max_attempts` is exhausted, or `None` when this
        worker no longer owns the lease and must not mutate the job."""
        now = SYSTEM_CLOCK.now()
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE ingest_job
                       SET status = CASE
                                      WHEN attempts >= max_attempts THEN 'failed'
                                      ELSE 'queued'
                                    END,
                           finished_at = CASE
                                           WHEN attempts >= max_attempts THEN :now
                                           ELSE finished_at
                                         END,
                           owner_id = NULL,
                           heartbeat_at = NULL,
                           lease_expires_at = CASE
                                                WHEN attempts >= max_attempts THEN NULL
                                                ELSE :now + make_interval(
                                                  secs => LEAST(
                                                    60,
                                                    5 * CAST(power(2, GREATEST(attempts - 1, 0)) AS integer)
                                                  )
                                                )
                                              END,
                           error_code = :error_code,
                           error_detail = :error_detail,
                           updated_at = :now
                     WHERE id = :id AND status = 'running' AND owner_id = :owner_id
                 RETURNING status
                    """
                ),
                {
                    "id": job_id,
                    "owner_id": owner_id,
                    "error_code": error_code,
                    "error_detail": error_detail,
                    "now": now,
                },
            )
            row = result.mappings().first()
            if row is None:
                return None
            next_status = str(row["status"])
            await session.execute(
                text(
                    """
                    INSERT INTO ingest_job_event (
                        org_id, job_id, from_status, to_status, owner_id, detail
                    )
                    VALUES (:org_id, :job_id, 'running', :status, :owner_id, :detail)
                    """
                ),
                {
                    "org_id": org_id,
                    "job_id": job_id,
                    "status": next_status,
                    "owner_id": owner_id,
                    "detail": error_detail,
                },
            )
        return next_status

    def _record(self, row: RowMapping, events: Sequence[IngestJobEventRecord]) -> IngestJobRecord:
        raw_payload = row["payload"]
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(str(raw_payload))
        return IngestJobRecord(
            id=JobId(row["id"]),
            org_id=OrgId(row["org_id"]),
            kind=str(row["kind"]),
            status=str(row["status"]),
            payload={str(key): str(value) for key, value in payload.items()},
            document_id=DocumentId(row["document_id"]) if row["document_id"] else None,
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            total_units=int(row["total_units"]),
            done_units=int(row["done_units"]),
            owner_id=str(row["owner_id"]) if row["owner_id"] else None,
            heartbeat_at=row["heartbeat_at"],
            lease_expires_at=row["lease_expires_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error_code=str(row["error_code"]) if row["error_code"] else None,
            error_detail=str(row["error_detail"]) if row["error_detail"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            events=tuple(events),
        )

    async def _events_for_jobs(
        self, *, session: AsyncSession, org_id: OrgId, job_ids: Sequence[JobId]
    ) -> dict[JobId, tuple[IngestJobEventRecord, ...]]:
        if not job_ids:
            return {}
        stmt = text(
            """
            SELECT id, job_id, from_status, to_status, owner_id, detail, occurred_at
              FROM ingest_job_event
             WHERE org_id = :org_id AND job_id IN :job_ids
             ORDER BY occurred_at, id
            """
        ).bindparams(bindparam("job_ids", expanding=True))
        result = await session.execute(stmt, {"org_id": org_id, "job_ids": list(job_ids)})
        grouped: dict[JobId, list[IngestJobEventRecord]] = {}
        for row in result.mappings():
            job_id = JobId(row["job_id"])
            grouped.setdefault(job_id, []).append(
                IngestJobEventRecord(
                    id=row["id"],
                    job_id=job_id,
                    from_status=str(row["from_status"]) if row["from_status"] else None,
                    to_status=str(row["to_status"]),
                    owner_id=str(row["owner_id"]) if row["owner_id"] else None,
                    detail=str(row["detail"]) if row["detail"] else None,
                    occurred_at=row["occurred_at"],
                )
            )
        return {job_id: tuple(events) for job_id, events in grouped.items()}
