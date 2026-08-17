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
    DocumentId,
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

# Reclaim only after the lease has been expired for a grace period. Reclaiming
# the instant a lease lapses races a worker that is merely slow, and two owners
# processing one job is worse than one job arriving late.
RECLAIM_GRACE_S = 30

_shutdown = asyncio.Event()


def _owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def reap_stuck_jobs(db: Database) -> int:
    """Move expired leases back to the queue. Returns how many were reclaimed."""
    cutoff = SYSTEM_CLOCK.now() - timedelta(seconds=RECLAIM_GRACE_S)

    # One statement: the UPDATE selects, transitions and records in a single
    # round trip, and `FOR UPDATE SKIP LOCKED` means two reapers racing cannot
    # both claim the same row. `elevated_session`, not `db.session()`: the
    # reaper is cross-tenant by nature (it sweeps every org's stuck jobs in
    # one pass), so there is no single `org_id` to scope this to — see the
    # module docstring for the bug this fixes.
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
                updated AS (
                    UPDATE ingest_job j
                       SET status = CASE
                                      WHEN j.attempts + 1 >= j.max_attempts THEN 'failed'
                                      ELSE 'queued'
                                    END,
                           attempts = j.attempts + 1,
                           owner_id = NULL,
                           heartbeat_at = NULL,
                           lease_expires_at = NULL,
                           error_code = 'lease_expired',
                           error_detail = 'worker stopped heartbeating; lease reclaimed'
                      FROM expired e
                     WHERE j.id = e.id
                 RETURNING j.id, j.org_id, j.status
                )
                INSERT INTO ingest_job_event (org_id, job_id, from_status, to_status, detail)
                SELECT org_id, id, 'running', status, 'reclaimed by reaper'
                  FROM updated
             RETURNING job_id
                """
            ),
            {"cutoff": cutoff},
        )
        reclaimed = len(result.fetchall())

    if reclaimed:
        log.warning("worker.reclaimed_stuck_jobs", count=reclaimed)
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
    job: ClaimedIngestJob,
    status: str,
    document_id: DocumentId | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Both, not either (TRACKER's `B1` deliverable 2 note, settled there):
    the Streams entry is durable, for a future consumer-group reader; the
    pub/sub publish is what an already-open WebSocket receives live, today.
    A worker that dies between the two leaves the Streams entry as the
    durable record of what happened even though no browser saw it arrive."""
    occurred_at = SYSTEM_CLOCK.now().isoformat()
    payload = {
        "type": "ingest_job",
        "job_id": str(job.id),
        "status": status,
        "kind": job.kind,
        "document_id": str(document_id) if document_id else None,
        "error_code": error_code,
        "occurred_at": occurred_at,
    }
    await cache.client.publish(_ingestion_channel(job.org_id), json.dumps(payload))

    stream = f"mnemos:events:org:{job.org_id}:ingestion"
    fields = {
        "job_id": str(job.id),
        "org_id": str(job.org_id),
        "status": status,
        "kind": job.kind,
        "document_id": str(document_id) if document_id else "",
        "error_code": error_code or "",
        "error_detail": error_detail or "",
        "occurred_at": occurred_at,
    }
    await event_bus.publish(stream, fields)


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
    await _publish_transition(cache=cache, event_bus=event_bus, job=job, status="running")

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
        )
    except Exception as exc:
        error_code = type(exc).__name__
        error_detail = str(exc)
        await jobs.mark_failed(
            job_id=job.id, org_id=job.org_id, error_code=error_code, error_detail=error_detail
        )
        await _publish_transition(
            cache=cache,
            event_bus=event_bus,
            job=job,
            status="failed",
            error_code=error_code,
            error_detail=error_detail,
        )
        log.error(
            "worker.job_failed",
            job_id=str(job.id),
            org_id=str(job.org_id),
            error_code=error_code,
            error_detail=error_detail,
        )
        return True

    await jobs.mark_succeeded(job_id=job.id, org_id=job.org_id, document_id=summary.id)
    await _publish_transition(
        cache=cache, event_bus=event_bus, job=job, status="succeeded", document_id=summary.id
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
                await reap_stuck_jobs(db)
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
