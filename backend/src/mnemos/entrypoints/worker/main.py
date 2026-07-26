"""Ingestion worker.

At this milestone the worker runs one real job: the **stuck-job reaper**.

A worker holding a job proves it is alive by advancing `heartbeat_at`. If it
dies — OOM, SIGKILL, a node disappearing — the row stays in `running` forever
and nothing retries it. The reaper is what turns that from a silent stall into a
recovery: a lease that expired is marked `stuck`, its attempt count is spent, and
it goes back to `queued` for another owner. Past `max_attempts` it fails loudly
instead of looping.

Every transition is appended to `ingest_job_event`, so a failure can be explained
afterwards rather than guessed at.

Document processing itself (extract, chunk, embed) lands in M6 and plugs into the
same claim/heartbeat protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
from datetime import timedelta

from sqlalchemy import text

from mnemos.core.clock import SYSTEM_CLOCK
from mnemos.core.config import get_settings
from mnemos.core.logging import configure_logging, get_logger
from mnemos.platform.db import Database

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
    # both claim the same row.
    async with db.session() as session:
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


async def run() -> None:
    settings = get_settings()
    configure_logging(json_output=not settings.is_local)
    db = Database(settings)

    owner = _owner_id()
    log.info("worker.startup", owner=owner, poll_interval_s=POLL_INTERVAL_S)

    try:
        while not _shutdown.is_set():
            try:
                await reap_stuck_jobs(db)
            except Exception as exc:
                log.error("worker.tick_failed", error=str(exc), error_type=type(exc).__name__)

            # Wait on the shutdown event rather than sleeping, so SIGTERM is
            # honoured immediately instead of after the full interval.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(_shutdown.wait(), timeout=POLL_INTERVAL_S)
    finally:
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
