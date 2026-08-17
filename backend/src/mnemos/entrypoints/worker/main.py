"""Ingestion worker.

**`B1` deliverable 4:** the worker now claims a real `queued` `ingest_job` and
actually processes it — extract, chunk, embed, via the same body `features/
knowledge/application/service.py`'s `upload_document` uses for a manual
upload, factored out into `KnowledgeService.ingest_connector_item` so neither
path duplicates the pipeline. Every transition (`queued -> running`,
`running -> succeeded`/`failed`) is appended to `ingest_job_event` and
published twice: to the Redis Streams `EventBus` (durable, for a future
consumer-group reader — `B2`) and to the `mnemos:org:{org_id}:ingestion`
pub/sub topic `entrypoints/realtime/main.py` already relays to an
authenticated WebSocket (live, deliverable 3's contract). Heartbeat/backoff
depth beyond one immediate failure is `B2`, deliberately not built here
(TRACKER §5's "explicitly not `B1`" list).

**A real, latent bug found and fixed while building the claim path:**
`reap_stuck_jobs` used to run inside `db.session()` with no `org_id` —
looking cross-tenant at every org's `running` jobs. Under `FORCE ROW LEVEL
SECURITY` (migration `0004`) and an unprivileged `mnemos_app` connection
(migration `0005`), an unscoped session's `app.current_org` GUC is never set,
so the org-isolation policy's `org_id = NULL` comparison is never true —
**the reaper saw zero rows on every real Postgres, always**, regardless of
how many jobs were actually stuck. Nothing caught this before because
nothing had ever exercised it against a real, RLS-enforced database (no test
existed). Fixed by moving it onto `db.elevated_session()` — `platform/db.py`
already reserved this as the second of "two callers, ever" (the first is
bootstrap), for exactly this shape of problem: a query that is legitimately
cross-tenant by nature, not a query that forgot to scope itself. The
worker's own claim (`IngestJobRepository.claim_next`) is the same shape and
uses the same escape hatch, for the same reason.

A worker holding a job proves it is alive by advancing `heartbeat_at`. If it
dies — OOM, SIGKILL, a node disappearing — the row stays in `running` forever
and nothing retries it. The reaper is what turns that from a silent stall into a
recovery: a lease that expired is marked `stuck`, its attempt count is spent, and
it goes back to `queued` for another owner. Past `max_attempts` it fails loudly
instead of looping.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import text

# Every model module, imported for its side effect on `Base.metadata` before
# any ORM operation runs — same reason `entrypoints/api/main.py` imports this.
# `content_source.org_id -> org.id`, `document.uploaded_by -> app_user.id` and
# `ingest_job.document_id -> document.id` all cross feature boundaries the
# worker's own imports below do not otherwise force to have run.
import mnemos.platform.models  # noqa: F401
from mnemos.core.clock import SYSTEM_CLOCK
from mnemos.core.config import get_settings
from mnemos.core.ids import DEFAULT_ID_GENERATOR
from mnemos.core.logging import configure_logging, get_logger
from mnemos.core.types import TrustTier
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.adapters.repository import ContentSourceRepository
from mnemos.features.connectors.application.factory import ConnectorFactory
from mnemos.features.connectors.application.service import ConnectorService
from mnemos.features.knowledge.adapters.jobs_repository import IngestJobRepository
from mnemos.features.knowledge.adapters.repository import KnowledgeRepository
from mnemos.features.knowledge.adapters.retrieval import SqlRetriever
from mnemos.features.knowledge.application.service import KnowledgeService
from mnemos.features.knowledge.domain import (
    ClaimedIngestJob,
    HashingEmbedder,
    HeuristicTokenizer,
)
from mnemos.platform.cache import Cache
from mnemos.platform.db import Database
from mnemos.platform.events.port import EventBus
from mnemos.platform.events.redis_streams import RedisStreamsEventBus
from mnemos.platform.objectstore.s3 import S3ObjectStore

log = get_logger(__name__)

POLL_INTERVAL_S = 5
LEASE_DURATION_S = 60
HEARTBEAT_INTERVAL_S = 15

# Reclaim only after the lease has been expired for a grace period. Reclaiming
# the instant a lease lapses races a worker that is merely slow, and two owners
# processing one job is worse than one job arriving late.
RECLAIM_GRACE_S = 30

_shutdown = asyncio.Event()


@dataclass(frozen=True, slots=True)
class ReapedJobTransition:
    id: object
    org_id: object
    kind: str
    status: str
    document_id: object | None
    attempts: int
    max_attempts: int
    done_units: int
    total_units: int
    error_code: str | None
    error_detail: str | None


def _owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def reap_stuck_jobs(db: Database) -> list[ReapedJobTransition]:
    """Surface expired leases as `stuck`, then either queue a retry or fail."""
    cutoff = SYSTEM_CLOCK.now() - timedelta(seconds=RECLAIM_GRACE_S)
    now = SYSTEM_CLOCK.now()
    retry_at = now + timedelta(seconds=POLL_INTERVAL_S)

    # The first UPDATE selects and marks expired jobs `stuck`; the follow-up
    # writes happen in the same transaction. `FOR UPDATE SKIP LOCKED` means two
    # reapers racing cannot both claim the same row. `elevated_session`, not
    # `db.session()`: the reaper is cross-tenant by nature, so there is no
    # single `org_id` to scope this to — see the module docstring for the bug
    # this fixes.
    async with db.elevated_session() as session:
        result = await session.execute(
            text(
                """
                WITH expired AS (
                    SELECT id FROM ingest_job
                     WHERE status = 'running'
                       AND lease_expires_at IS NOT NULL
                       AND lease_expires_at < :cutoff
                     FOR UPDATE SKIP LOCKED
                ),
                stuck AS (
                    UPDATE ingest_job j
                       SET status = 'stuck',
                           owner_id = NULL,
                           heartbeat_at = NULL,
                           lease_expires_at = NULL,
                           error_code = 'lease_expired',
                           error_detail = 'worker stopped heartbeating; lease reclaimed'
                      FROM expired e
                     WHERE j.id = e.id
                 RETURNING j.id, j.org_id, j.kind, j.document_id, j.attempts, j.max_attempts,
                           j.done_units, j.total_units, j.error_code, j.error_detail
                )
                SELECT id, org_id, kind, document_id, attempts, max_attempts,
                       done_units, total_units, error_code, error_detail
                  FROM stuck
                """
            ),
            {"cutoff": cutoff},
        )
        stuck_rows = list(result.mappings())
        rows = []
        for row in stuck_rows:
            next_attempts = int(row["attempts"]) + 1
            next_status = "failed" if next_attempts >= int(row["max_attempts"]) else "queued"
            await session.execute(
                text(
                    """
                    INSERT INTO ingest_job_event (org_id, job_id, from_status, to_status, detail)
                    VALUES (:org_id, :job_id, 'running', 'stuck', 'worker lease expired')
                    """
                ),
                {"org_id": row["org_id"], "job_id": row["id"]},
            )
            await session.execute(
                text(
                    """
                    UPDATE ingest_job
                       SET status = :status,
                           attempts = :attempts,
                           lease_expires_at = :retry_at,
                           finished_at = :finished_at
                     WHERE id = :id
                    """
                ),
                {
                    "id": row["id"],
                    "status": next_status,
                    "attempts": next_attempts,
                    "retry_at": retry_at if next_status == "queued" else None,
                    "finished_at": now if next_status == "failed" else None,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO ingest_job_event (org_id, job_id, from_status, to_status, detail)
                    VALUES (:org_id, :job_id, 'stuck', :status, :detail)
                    """
                ),
                {
                    "org_id": row["org_id"],
                    "job_id": row["id"],
                    "status": next_status,
                    "detail": "retry queued after expired lease"
                    if next_status == "queued"
                    else "max attempts exhausted after expired lease",
                },
            )
            rows.append({**row, "status": next_status, "attempts": next_attempts})

    reclaimed = [
        ReapedJobTransition(
            id=row["id"],
            org_id=row["org_id"],
            kind=str(row["kind"]),
            status=str(row["status"]),
            document_id=row["document_id"],
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            done_units=int(row["done_units"]),
            total_units=int(row["total_units"]),
            error_code=str(row["error_code"]) if row["error_code"] else None,
            error_detail=str(row["error_detail"]) if row["error_detail"] else None,
        )
        for row in rows
    ]
    if reclaimed:
        log.warning("worker.reclaimed_stuck_jobs", count=len(reclaimed))
    return reclaimed


def _ingestion_channel(org_id: object) -> str:
    """`entrypoints/realtime/main.py`'s `/ws/ingestion` contract, verbatim
    (`B1` deliverable 3): the gateway derives this exact topic from the
    caller's own token and refuses any other `channel` path segment, so a
    publish anywhere else is invisible to every subscriber. Duplicated as a
    one-line f-string rather than imported — `entrypoints/*` are separate
    processes/images, and `platform/` (below both) has no `OrgId` type to
    hang a shared helper on without pulling `features.identity` under it."""
    return f"mnemos:org:{org_id}:ingestion"


async def _publish_transition(
    *,
    cache: Cache,
    event_bus: EventBus,
    job_id: object,
    org_id: object,
    kind: str,
    status: str,
    document_id: object | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    attempts: int | None = None,
    max_attempts: int | None = None,
    done_units: int | None = None,
    total_units: int | None = None,
) -> None:
    """Both, not either (TRACKER's `B1` deliverable 2 note, settled there):
    the Streams entry is durable, for a future consumer-group reader; the
    pub/sub publish is what an already-open WebSocket receives live, today.
    A worker that dies between the two leaves the Streams entry as the
    durable record of what happened even though no browser saw it arrive."""
    occurred_at = SYSTEM_CLOCK.now().isoformat()
    payload = {
        "type": "ingest_job",
        "job_id": str(job_id),
        "status": status,
        "kind": kind,
        "document_id": str(document_id) if document_id else None,
        "error_code": error_code,
        "error_detail": error_detail,
        "attempts": attempts,
        "max_attempts": max_attempts,
        "done_units": done_units,
        "total_units": total_units,
        "occurred_at": occurred_at,
    }
    await cache.client.publish(_ingestion_channel(org_id), json.dumps(payload))

    stream = f"mnemos:events:org:{org_id}:ingestion"
    fields = {
        "job_id": str(job_id),
        "org_id": str(org_id),
        "status": status,
        "kind": kind,
        "document_id": str(document_id) if document_id else "",
        "error_code": error_code or "",
        "error_detail": error_detail or "",
        "attempts": str(attempts) if attempts is not None else "",
        "max_attempts": str(max_attempts) if max_attempts is not None else "",
        "done_units": str(done_units) if done_units is not None else "",
        "total_units": str(total_units) if total_units is not None else "",
        "occurred_at": occurred_at,
    }
    await event_bus.publish(stream, fields)


async def _heartbeat_until_stopped(
    *,
    jobs: IngestJobRepository,
    job: ClaimedIngestJob,
    owner: str,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_S)
            return
        renewed = await jobs.heartbeat(
            job_id=job.id,
            org_id=job.org_id,
            owner_id=owner,
            lease_seconds=LEASE_DURATION_S,
        )
        if not renewed:
            log.warning("worker.heartbeat_lost", job_id=str(job.id), org_id=str(job.org_id))
            return


async def process_next_job(
    *,
    jobs: IngestJobRepository,
    connectors: ConnectorService,
    knowledge: KnowledgeService,
    cache: Cache,
    event_bus: EventBus,
    owner: str,
) -> bool:
    """Claim one `queued` job and run it to completion. Returns whether a job
    was claimed at all, so `run()`'s tick can drain the queue instead of
    processing one job per `POLL_INTERVAL_S`."""
    job = await jobs.claim_next(owner_id=owner, lease_seconds=LEASE_DURATION_S)
    if job is None:
        return False

    log.info("worker.job_claimed", job_id=str(job.id), org_id=str(job.org_id), kind=job.kind)
    await jobs.record_progress(job_id=job.id, org_id=job.org_id, done_units=0, total_units=4)
    await _publish_transition(
        cache=cache,
        event_bus=event_bus,
        job_id=job.id,
        org_id=job.org_id,
        kind=job.kind,
        status="running",
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        done_units=0,
        total_units=4,
    )

    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_until_stopped(jobs=jobs, job=job, owner=owner, stop=heartbeat_stop)
    )

    async def progress(done_units: int, total_units: int, detail: str) -> None:
        await jobs.record_progress(
            job_id=job.id,
            org_id=job.org_id,
            done_units=done_units,
            total_units=total_units,
            detail=detail,
        )
        await _publish_transition(
            cache=cache,
            event_bus=event_bus,
            job_id=job.id,
            org_id=job.org_id,
            kind=job.kind,
            status="running",
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            done_units=done_units,
            total_units=total_units,
        )

    try:
        source_slug = job.payload["source_slug"]
        item_uri = job.payload["item_uri"]
        item_name = job.payload.get("item_name") or item_uri
        content_type = job.payload.get("content_type") or "application/octet-stream"

        source_kind, data = await connectors.fetch_item(
            org_id=job.org_id, slug=source_slug, uri=item_uri
        )
        summary = await knowledge.ingest_connector_item(
            org_id=job.org_id,
            title=item_name,
            media_type=content_type,
            data=data,
            source_kind=source_kind,
            source_uri=item_uri,
            trust_tier=int(TrustTier.RETRIEVED),
            progress=progress,
        )
    except Exception as exc:
        error_code = type(exc).__name__
        error_detail = str(exc)
        next_status = await jobs.mark_attempt_failed(
            job_id=job.id, org_id=job.org_id, error_code=error_code, error_detail=error_detail
        )
        await _publish_transition(
            cache=cache,
            event_bus=event_bus,
            job_id=job.id,
            org_id=job.org_id,
            kind=job.kind,
            status=next_status,
            error_code=error_code,
            error_detail=error_detail,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            done_units=0,
            total_units=4,
        )
        log.error(
            "worker.job_failed" if next_status == "failed" else "worker.job_retry_queued",
            job_id=str(job.id),
            org_id=str(job.org_id),
            error_code=error_code,
            error_detail=error_detail,
            next_status=next_status,
        )
        return True
    finally:
        heartbeat_stop.set()
        await heartbeat_task

    await jobs.mark_succeeded(job_id=job.id, org_id=job.org_id, document_id=summary.id)
    await _publish_transition(
        cache=cache,
        event_bus=event_bus,
        job_id=job.id,
        org_id=job.org_id,
        kind=job.kind,
        status="succeeded",
        document_id=summary.id,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        done_units=4,
        total_units=4,
    )
    log.info(
        "worker.job_succeeded",
        job_id=str(job.id),
        org_id=str(job.org_id),
        document_id=str(summary.id),
    )
    return True


async def run() -> None:
    settings = get_settings()
    configure_logging(
        json_output=not settings.is_local, session_log_enabled=settings.session_log_enabled
    )
    db = Database(settings)
    cache = Cache(settings)
    event_bus = RedisStreamsEventBus(cache.client)
    http_client = httpx.AsyncClient()

    cipher = SourceConfigCipher(settings.source_encryption_key.get_secret_value())
    connectors = ConnectorService(
        repository=ContentSourceRepository(db, DEFAULT_ID_GENERATOR),
        cipher=cipher,
        factory=ConnectorFactory(settings=settings, cipher=cipher, http_client=http_client),
        local_fs_allowed_roots=settings.local_fs_allowed_roots,
    )
    object_store = S3ObjectStore(
        endpoint_url=settings.object_endpoint,
        access_key=settings.object_access_key,
        secret_key=settings.object_secret_key.get_secret_value(),
        bucket=settings.object_bucket,
        region=settings.object_region,
    )
    knowledge = KnowledgeService(
        repository=KnowledgeRepository(db, DEFAULT_ID_GENERATOR),
        retriever=SqlRetriever(db),
        objects=object_store,
        embedder=HashingEmbedder(dim=settings.embedding_dim),
        tokenizer=HeuristicTokenizer(),
        rrf_k=settings.rrf_k,
        near_duplicate_threshold=settings.near_duplicate_threshold,
    )
    jobs = IngestJobRepository(db, DEFAULT_ID_GENERATOR)

    owner = _owner_id()
    log.info("worker.startup", owner=owner, poll_interval_s=POLL_INTERVAL_S)

    try:
        while not _shutdown.is_set():
            try:
                for reaped in await reap_stuck_jobs(db):
                    await _publish_transition(
                        cache=cache,
                        event_bus=event_bus,
                        job_id=reaped.id,
                        org_id=reaped.org_id,
                        kind=reaped.kind,
                        status="stuck",
                        document_id=reaped.document_id,
                        error_code="lease_expired",
                        error_detail=reaped.error_detail,
                        attempts=reaped.attempts,
                        max_attempts=reaped.max_attempts,
                        done_units=reaped.done_units,
                        total_units=reaped.total_units,
                    )
                    await _publish_transition(
                        cache=cache,
                        event_bus=event_bus,
                        job_id=reaped.id,
                        org_id=reaped.org_id,
                        kind=reaped.kind,
                        status=reaped.status,
                        document_id=reaped.document_id,
                        error_code=reaped.error_code,
                        error_detail=reaped.error_detail,
                        attempts=reaped.attempts,
                        max_attempts=reaped.max_attempts,
                        done_units=reaped.done_units,
                        total_units=reaped.total_units,
                    )
            except Exception as exc:
                log.error("worker.tick_failed", error=str(exc), error_type=type(exc).__name__)

            try:
                # Drain the queue each tick rather than one job per
                # `POLL_INTERVAL_S` — heartbeat/backoff pacing beyond one
                # immediate failure is `B2`, not this loop's job.
                while await process_next_job(
                    jobs=jobs,
                    connectors=connectors,
                    knowledge=knowledge,
                    cache=cache,
                    event_bus=event_bus,
                    owner=owner,
                ):
                    pass
            except Exception as exc:
                log.error(
                    "worker.job_processing_failed", error=str(exc), error_type=type(exc).__name__
                )

            # Wait on the shutdown event rather than sleeping, so SIGTERM is
            # honoured immediately instead of after the full interval.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(_shutdown.wait(), timeout=POLL_INTERVAL_S)
    finally:
        await http_client.aclose()
        await cache.close()
        await db.dispose()
        log.info("worker.shutdown", owner=owner)


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown.set)
    loop.run_until_complete(run())


if __name__ == "__main__":
    main()
