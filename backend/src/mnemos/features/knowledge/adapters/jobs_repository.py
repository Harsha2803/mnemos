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
from collections.abc import Mapping
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mnemos.core.clock import SYSTEM_CLOCK
from mnemos.core.errors import ConflictError
from mnemos.core.ids import IdGenerator
from mnemos.features.identity.domain import OrgId
from mnemos.features.knowledge.adapters.models import IngestJob
from mnemos.features.knowledge.domain import ClaimedIngestJob, DocumentId, JobId
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

    async def mark_succeeded(
        self, *, job_id: JobId, org_id: OrgId, document_id: DocumentId
    ) -> None:
        async with self._db.session(org_id=org_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE ingest_job
                       SET status = 'succeeded', document_id = :document_id,
                           finished_at = :now, owner_id = NULL, heartbeat_at = NULL,
                           lease_expires_at = NULL
                     WHERE id = :id
                    """
                ),
                {"id": job_id, "document_id": document_id, "now": SYSTEM_CLOCK.now()},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO ingest_job_event (org_id, job_id, from_status, to_status, detail)
                    VALUES (:org_id, :job_id, 'running', 'succeeded', 'ingested')
                    """
                ),
                {"org_id": org_id, "job_id": job_id},
            )

    async def mark_failed(
        self, *, job_id: JobId, org_id: OrgId, error_code: str, error_detail: str
    ) -> None:
        async with self._db.session(org_id=org_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE ingest_job
                       SET status = 'failed', error_code = :error_code, error_detail = :error_detail,
                           finished_at = :now, owner_id = NULL, heartbeat_at = NULL,
                           lease_expires_at = NULL
                     WHERE id = :id
                    """
                ),
                {
                    "id": job_id,
                    "error_code": error_code,
                    "error_detail": error_detail,
                    "now": SYSTEM_CLOCK.now(),
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO ingest_job_event (org_id, job_id, from_status, to_status, detail)
                    VALUES (:org_id, :job_id, 'running', 'failed', :detail)
                    """
                ),
                {"org_id": org_id, "job_id": job_id, "detail": error_detail},
            )
