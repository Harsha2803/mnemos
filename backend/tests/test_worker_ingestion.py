"""`B1` deliverable 4 — the worker's claim-and-process path, against a real
Postgres and a real Redis.

Two things a fake could not prove, so this file does not use one:

1. **`IngestJobRepository.claim_next` and `reap_stuck_jobs` are correct under
   `FORCE ROW LEVEL SECURITY`.** `db.elevated_session()` is the fix for a real
   bug found while writing this file: both queries are cross-tenant by
   nature (a worker claims across every org's queue, a reaper sweeps every
   org's stuck jobs), and the ordinary `db.session()` — no `org_id`, so the
   `app.current_org` GUC is never set — makes the org-isolation policy's
   `org_id = NULL` comparison false for every row, always. A fake session
   has no RLS to get this wrong against.
2. **The two publishes actually reach a real Redis Streams entry and a real
   pub/sub subscriber**, in the exact shapes deliverable 2 and deliverable 3
   already committed to: the stream, and the `mnemos:org:{org_id}:ingestion`
   topic `test_realtime_auth.py` proves the gateway relays.

Only the object store is faked (`InMemoryObjectStore`, same class
`test_knowledge_endpoints.py` uses) — nothing here is about MinIO.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from pydantic import SecretStr
from redis.asyncio import Redis

import mnemos.platform.models  # noqa: F401
from mnemos.core.config import Settings
from mnemos.core.errors import ConflictError
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.entrypoints.worker.main import process_next_job, reap_stuck_jobs
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.adapters.repository import ContentSourceRepository
from mnemos.features.connectors.application.factory import ConnectorFactory
from mnemos.features.connectors.application.service import ConnectorService
from mnemos.features.identity.domain import OrgId
from mnemos.features.knowledge.adapters.jobs_repository import IngestJobRepository
from mnemos.features.knowledge.adapters.repository import KnowledgeRepository
from mnemos.features.knowledge.adapters.retrieval import SqlRetriever
from mnemos.features.knowledge.application.service import KnowledgeService
from mnemos.features.knowledge.domain import (
    CONNECTOR_INGEST_KIND,
    HashingEmbedder,
    HeuristicTokenizer,
)
from mnemos.platform.cache import Cache
from mnemos.platform.db import Database
from mnemos.platform.events.redis_streams import RedisStreamsEventBus

from .conftest import APP_PASSWORD, Postgres

SOURCE_KEY = "zyE7WKGQXXwuWC7pvMVZ3qbkXUliL3BRmD8Lzk89qu4="
EMBEDDING_DIM = 384
OWNER = "test-worker:1"


class InMemoryObjectStore:
    """Same reasoning `test_knowledge_endpoints.py`'s copy documents: the S3
    adapter is boto3 over MinIO and proves nothing about the worker."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest_asyncio.fixture
async def org_id(postgres: Postgres) -> AsyncIterator[OrgId]:
    new_org = OrgId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            new_org,
            f"worker-org-{new_org.hex[:8]}",
            "Worker Test Org",
        )
        yield new_org
        await conn.execute("DELETE FROM org WHERE id = $1", new_org)
    finally:
        await conn.close()


@pytest.fixture
def settings(postgres: Postgres, redis_url: str, tmp_path: Path) -> Settings:
    return Settings(
        env="test",  # type: ignore[arg-type]
        database_url=postgres.app_url,
        app_database_password=APP_PASSWORD,  # type: ignore[arg-type]
        redis_url=redis_url,
        source_encryption_key=SecretStr(SOURCE_KEY),
        local_fs_allowed_roots=[str(tmp_path)],
    )


@pytest_asyncio.fixture
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings)
    try:
        yield database
    finally:
        await database.dispose()


@pytest_asyncio.fixture
async def cache(settings: Settings) -> AsyncIterator[Cache]:
    c = Cache(settings)
    try:
        yield c
    finally:
        await c.close()


@pytest.fixture
def event_bus(cache: Cache) -> RedisStreamsEventBus:
    return RedisStreamsEventBus(cache.client)


@pytest.fixture
def objects() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest_asyncio.fixture
async def connectors(db: Database, settings: Settings) -> AsyncIterator[ConnectorService]:
    import httpx

    http_client = httpx.AsyncClient()
    cipher = SourceConfigCipher(SOURCE_KEY)
    try:
        yield ConnectorService(
            repository=ContentSourceRepository(db, Uuid7Generator()),
            cipher=cipher,
            factory=ConnectorFactory(settings=settings, cipher=cipher, http_client=http_client),
            local_fs_allowed_roots=settings.local_fs_allowed_roots,
        )
    finally:
        await http_client.aclose()


@pytest.fixture
def knowledge(db: Database, objects: InMemoryObjectStore) -> KnowledgeService:
    return KnowledgeService(
        repository=KnowledgeRepository(db, Uuid7Generator()),
        retriever=SqlRetriever(db),
        objects=objects,
        embedder=HashingEmbedder(dim=EMBEDDING_DIM),
        tokenizer=HeuristicTokenizer(),
        rrf_k=60,
        near_duplicate_threshold=0.86,
    )


@pytest.fixture
def jobs(db: Database) -> IngestJobRepository:
    return IngestJobRepository(db, Uuid7Generator())


@pytest_asyncio.fixture
async def pubsub_client(redis_url: str) -> AsyncIterator[Redis]:
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def _enqueue_fixture_item(
    *,
    connectors: ConnectorService,
    jobs: IngestJobRepository,
    org_id: OrgId,
    root: Path,
    name: str,
    body: str,
) -> str:
    (root / name).write_text(body)
    await connectors.register(
        org_id=org_id, slug="fixtures", name="Fixtures", kind="local_fs", config={"root": str(root)}
    )
    items = await connectors.list_items(org_id=org_id, slug="fixtures")
    item = next(i for i in items if i.name == name)
    await jobs.enqueue(
        org_id=org_id,
        kind=CONNECTOR_INGEST_KIND,
        payload={
            "source_slug": "fixtures",
            "item_uri": item.uri,
            "item_name": item.name,
            "content_type": item.content_type,
        },
        idempotency_key=f"fixtures:{item.uri}",
    )
    return item.uri


async def _job_row_by_kind(postgres: Postgres, *, org_id: OrgId, kind: str) -> asyncpg.Record:
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM ingest_job WHERE org_id = $1 AND kind = $2", org_id, kind
        )
        assert row is not None
        return row
    finally:
        await conn.close()


async def _fetch_events(postgres: Postgres, job_id: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        return list(
            await conn.fetch(
                "SELECT * FROM ingest_job_event WHERE job_id = $1 ORDER BY occurred_at", job_id
            )
        )
    finally:
        await conn.close()


# --------------------------------------------------------------- claim_next


async def test_claim_next_claims_the_oldest_queued_job_first(
    jobs: IngestJobRepository, org_id: OrgId
) -> None:
    first = await jobs.enqueue(org_id=org_id, kind="t", payload={"n": "1"})
    await jobs.enqueue(org_id=org_id, kind="t", payload={"n": "2"})

    claimed = await jobs.claim_next(owner_id=OWNER, lease_seconds=60)

    assert claimed is not None
    assert str(claimed.id) == str(first)
    assert claimed.org_id == org_id
    assert claimed.payload == {"n": "1"}
    assert claimed.attempts == 1


async def test_claim_next_returns_none_when_the_queue_is_empty(jobs: IngestJobRepository) -> None:
    assert await jobs.claim_next(owner_id=OWNER, lease_seconds=60) is None


async def test_claim_next_skips_a_queued_job_until_its_retry_delay_passes(
    jobs: IngestJobRepository, postgres: Postgres, org_id: OrgId
) -> None:
    job_id = await jobs.enqueue(org_id=org_id, kind="t", payload={"n": "retry"})
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "UPDATE ingest_job SET lease_expires_at = now() + interval '30 seconds' WHERE id = $1",
            job_id,
        )
    finally:
        await conn.close()

    assert await jobs.claim_next(owner_id=OWNER, lease_seconds=60) is None


async def test_two_concurrent_claimers_never_claim_the_same_job(
    jobs: IngestJobRepository, org_id: OrgId
) -> None:
    """`FOR UPDATE SKIP LOCKED`, proved under real concurrency rather than
    asserted from reading the SQL — the same claim `reap_stuck_jobs` already
    makes about its own query."""
    for i in range(6):
        await jobs.enqueue(org_id=org_id, kind="t", payload={"n": str(i)})

    results = await asyncio.gather(
        *(jobs.claim_next(owner_id=f"worker-{i}", lease_seconds=60) for i in range(6))
    )

    claimed_ids = [r.id for r in results if r is not None]
    assert len(claimed_ids) == 6
    assert len(set(claimed_ids)) == 6  # no two claimers got the same row


async def test_enqueue_is_idempotent_per_item(jobs: IngestJobRepository, org_id: OrgId) -> None:
    await jobs.enqueue(org_id=org_id, kind="t", payload={}, idempotency_key="fixtures:a.txt")

    with pytest.raises(ConflictError):
        await jobs.enqueue(org_id=org_id, kind="t", payload={}, idempotency_key="fixtures:a.txt")


async def test_heartbeat_extends_the_running_jobs_lease(
    jobs: IngestJobRepository, postgres: Postgres, org_id: OrgId
) -> None:
    job_id = await jobs.enqueue(org_id=org_id, kind="t", payload={})
    claimed = await jobs.claim_next(owner_id=OWNER, lease_seconds=10)
    assert claimed is not None

    renewed = await jobs.heartbeat(job_id=job_id, org_id=org_id, owner_id=OWNER, lease_seconds=120)

    assert renewed is True
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT owner_id, heartbeat_at, lease_expires_at FROM ingest_job WHERE id = $1",
            job_id,
        )
        assert row is not None
        assert row["owner_id"] == OWNER
        assert row["heartbeat_at"] is not None
        assert row["lease_expires_at"] is not None
    finally:
        await conn.close()


# ------------------------------------------------------------ process a job


async def test_process_next_job_ingests_a_connector_item_end_to_end(
    jobs: IngestJobRepository,
    connectors: ConnectorService,
    knowledge: KnowledgeService,
    cache: Cache,
    event_bus: RedisStreamsEventBus,
    pubsub_client: Redis,
    postgres: Postgres,
    org_id: OrgId,
    tmp_path: Path,
) -> None:
    body = "\n\n".join(f"Paragraph {i} about the quarterly close." for i in range(8))
    await _enqueue_fixture_item(
        connectors=connectors, jobs=jobs, org_id=org_id, root=tmp_path, name="close.txt", body=body
    )

    topic = f"mnemos:org:{org_id}:ingestion"
    pubsub = pubsub_client.pubsub()
    await pubsub.subscribe(topic)
    await pubsub.get_message(timeout=1)  # the subscribe confirmation itself

    claimed = await process_next_job(
        jobs=jobs,
        connectors=connectors,
        knowledge=knowledge,
        cache=cache,
        event_bus=event_bus,
        owner=OWNER,
    )
    assert claimed is True

    # -- the ingest_job row and its event history --------------------------
    job_row = await _job_row_by_kind(postgres, org_id=org_id, kind=CONNECTOR_INGEST_KIND)
    assert job_row["status"] == "succeeded"
    assert job_row["document_id"] is not None
    assert job_row["finished_at"] is not None

    events = await _fetch_events(postgres, job_row["id"])
    transitions = [(e["from_status"], e["to_status"]) for e in events]
    assert transitions[0] == ("queued", "running")
    assert ("running", "running") in transitions
    assert transitions[-1] == ("running", "succeeded")
    assert job_row["done_units"] == job_row["total_units"] == 4

    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        document = await conn.fetchrow(
            "SELECT source_kind, source_uri, trust_tier, uploaded_by FROM document WHERE id = $1",
            job_row["document_id"],
        )
        assert document is not None
        assert document["source_kind"] == "local_fs"
        assert document["source_uri"] == "close.txt"
        assert document["trust_tier"] == 10  # TrustTier.RETRIEVED — see the service docstring
        assert document["uploaded_by"] is None  # nobody is signed in for a connector ingest

        chunk_count = await conn.fetchval(
            "SELECT count(*) FROM chunk WHERE document_id = $1", job_row["document_id"]
        )
        assert chunk_count > 0
    finally:
        await conn.close()

    # -- the live pub/sub relay ------------------------------------------
    seen: list[dict[str, object]] = []
    for _ in range(8):
        message = await pubsub.get_message(timeout=2)
        if message and message["type"] == "message":
            seen.append(json.loads(message["data"]))
            if seen[-1]["status"] == "succeeded":
                break
    statuses = [m["status"] for m in seen]
    assert next(iter(statuses)) == "running"
    assert statuses[-1] == "succeeded"
    assert seen[-1]["done_units"] == 4
    assert seen[-1]["total_units"] == 4
    assert all(m["job_id"] == str(job_row["id"]) for m in seen)
    await pubsub.unsubscribe(topic)
    await pubsub.aclose()

    # -- the durable Streams entry ----------------------------------------
    stream = f"mnemos:events:org:{org_id}:ingestion"
    raw_entries = await cache.client.xrange(stream, "-", "+")
    assert len(raw_entries) >= 3
    statuses = [fields["status"] for _entry_id, fields in raw_entries]
    assert statuses[0] == "running"
    assert statuses[-1] == "succeeded"


async def test_process_next_job_marks_a_missing_item_as_failed(
    jobs: IngestJobRepository,
    connectors: ConnectorService,
    knowledge: KnowledgeService,
    cache: Cache,
    event_bus: RedisStreamsEventBus,
    postgres: Postgres,
    org_id: OrgId,
    tmp_path: Path,
) -> None:
    """A job can outlive the file it points at — the item is deleted between
    `list-items` and the worker claiming it. `LocalFsConnector.fetch` raises
    `NotFoundError`; the job must fail with that recorded, not crash the
    worker's tick."""
    await connectors.register(
        org_id=org_id,
        slug="fixtures",
        name="Fixtures",
        kind="local_fs",
        config={"root": str(tmp_path)},
    )
    await jobs.enqueue(
        org_id=org_id,
        kind=CONNECTOR_INGEST_KIND,
        payload={
            "source_slug": "fixtures",
            "item_uri": "never-existed.txt",
            "item_name": "never-existed.txt",
            "content_type": "text/plain",
        },
    )
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "UPDATE ingest_job SET max_attempts = 1 WHERE org_id = $1 AND kind = $2",
            org_id,
            CONNECTOR_INGEST_KIND,
        )
    finally:
        await conn.close()

    claimed = await process_next_job(
        jobs=jobs,
        connectors=connectors,
        knowledge=knowledge,
        cache=cache,
        event_bus=event_bus,
        owner=OWNER,
    )
    assert claimed is True

    job_row = await _job_row_by_kind(postgres, org_id=org_id, kind=CONNECTOR_INGEST_KIND)
    assert job_row["status"] == "failed"
    assert job_row["document_id"] is None
    assert job_row["error_code"] == "NotFoundError"
    assert job_row["error_detail"]

    events = await _fetch_events(postgres, job_row["id"])
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        ("queued", "running"),
        ("running", "failed"),
    ]


async def test_process_next_job_retries_a_failed_attempt_before_terminal_failure(
    jobs: IngestJobRepository,
    connectors: ConnectorService,
    knowledge: KnowledgeService,
    cache: Cache,
    event_bus: RedisStreamsEventBus,
    postgres: Postgres,
    org_id: OrgId,
    tmp_path: Path,
) -> None:
    await connectors.register(
        org_id=org_id,
        slug="fixtures",
        name="Fixtures",
        kind="local_fs",
        config={"root": str(tmp_path)},
    )
    await jobs.enqueue(
        org_id=org_id,
        kind=CONNECTOR_INGEST_KIND,
        payload={
            "source_slug": "fixtures",
            "item_uri": "not-yet-there.txt",
            "item_name": "not-yet-there.txt",
            "content_type": "text/plain",
        },
    )

    claimed = await process_next_job(
        jobs=jobs,
        connectors=connectors,
        knowledge=knowledge,
        cache=cache,
        event_bus=event_bus,
        owner=OWNER,
    )
    assert claimed is True

    job_row = await _job_row_by_kind(postgres, org_id=org_id, kind=CONNECTOR_INGEST_KIND)
    assert job_row["status"] == "queued"
    assert job_row["attempts"] == 1
    assert job_row["lease_expires_at"] is not None
    assert job_row["error_code"] == "NotFoundError"

    events = await _fetch_events(postgres, job_row["id"])
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        ("queued", "running"),
        ("running", "queued"),
    ]


# -------------------------------------------------------------------- reap


async def test_reap_stuck_jobs_reclaims_an_expired_lease_under_real_rls(
    db: Database, postgres: Postgres, org_id: OrgId
) -> None:
    """The regression test for the bug this deliverable found: before the fix,
    `reap_stuck_jobs` ran in an unscoped `db.session()`, and RLS's `org_id =
    NULL` comparison made every `running` row invisible to it — this test
    would have seen zero rows reclaimed on a real, RLS-enforced Postgres no
    matter how expired the lease was."""
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        job_id = uuid7()
        await conn.execute(
            """
            INSERT INTO ingest_job (id, org_id, kind, status, owner_id, heartbeat_at,
                                     lease_expires_at, attempts, max_attempts)
            VALUES ($1, $2, 'connector_ingest', 'running', 'dead-worker:1',
                    now() - interval '2 minutes', now() - interval '90 seconds', 0, 3)
            """,
            job_id,
            org_id,
        )
    finally:
        await conn.close()

    reclaimed = await reap_stuck_jobs(db)
    assert len(reclaimed) == 1
    assert reclaimed[0].status == "queued"

    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT status, owner_id, attempts FROM ingest_job WHERE id = $1", job_id
        )
        assert row is not None
        assert row["status"] == "queued"
        assert row["owner_id"] is None
        assert row["attempts"] == 1
    finally:
        await conn.close()

    events = await _fetch_events(postgres, job_id)
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        ("running", "stuck"),
        ("stuck", "queued"),
    ]
