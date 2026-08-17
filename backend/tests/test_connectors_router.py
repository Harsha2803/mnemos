"""`B1` deliverable 5's backend slice — `/api/v1/connectors` over a real
Postgres.

Only the object store equivalent (there is none here — the local-fs
connector reads `tmp_path` directly) is faked; everything else, including
cross-org isolation, is asserted against real RLS the same way
`test_knowledge_endpoints.py` and `test_worker_ingestion.py` do — a fake
repository would only prove the fake.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.entrypoints.api.main import create_app
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.adapters.repository import ContentSourceRepository
from mnemos.features.connectors.application.factory import ConnectorFactory
from mnemos.features.connectors.application.service import ConnectorService
from mnemos.features.identity.adapters.principals import SqlPrincipalRepository
from mnemos.features.identity.application.principals import PrincipalResolver
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.features.knowledge.adapters.jobs_repository import IngestJobRepository
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
SOURCE_KEY = "zyE7WKGQXXwuWC7pvMVZ3qbkXUliL3BRmD8Lzk89qu4="
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


class Seed:
    def __init__(
        self,
        org_a: OrgId,
        user_a: UserId,
        session_a: SessionId,
        org_b: OrgId,
        user_b: UserId,
        session_b: SessionId,
    ) -> None:
        self.org_a = org_a
        self.user_a = user_a
        self.session_a = session_a
        self.org_b = org_b
        self.user_b = user_b
        self.session_b = session_b


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    ids = Seed(
        org_a=OrgId(uuid7()),
        user_a=UserId(uuid7()),
        session_a=SessionId(uuid7()),
        org_b=OrgId(uuid7()),
        user_b=UserId(uuid7()),
        session_b=SessionId(uuid7()),
    )
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        for org_id, slug, user_id, session_id, email in (
            (ids.org_a, "cn-org-a", ids.user_a, ids.session_a, "ada@cn.test"),
            (ids.org_b, "cn-org-b", ids.user_b, ids.session_b, "bob@cn.test"),
        ):
            await conn.execute(
                "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)", org_id, slug, slug
            )
            await conn.execute(
                "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
                user_id,
                org_id,
                email,
                email,
            )
            await conn.execute(
                "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
                "VALUES ($1, $2, $3, $4, $5)",
                session_id,
                org_id,
                user_id,
                f"hash-for-{slug}",
                NOW + timedelta(days=14),
            )
        yield ids
        await conn.execute("DELETE FROM org WHERE id = ANY($1::uuid[])", [ids.org_a, ids.org_b])
    finally:
        await conn.close()


@pytest.fixture
def settings(postgres: Postgres, tmp_path: Path) -> Settings:
    return Settings(
        env="test",  # type: ignore[arg-type]
        database_url=postgres.app_url,
        app_database_password=APP_PASSWORD,  # type: ignore[arg-type]
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


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def codec(clock: FrozenClock) -> PlatformTokenCodec:
    return PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER), clock=clock, ids=Uuid7Generator()
    )


@pytest.fixture
def client(
    codec: PlatformTokenCodec, clock: FrozenClock, db: Database, settings: Settings
) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(
            codec=codec, repository=SqlPrincipalRepository(db), clock=clock
        )
        http_client = httpx.AsyncClient()
        cipher = SourceConfigCipher(SOURCE_KEY)
        app.state.connector_service = ConnectorService(
            repository=ContentSourceRepository(db, Uuid7Generator()),
            cipher=cipher,
            factory=ConnectorFactory(settings=settings, cipher=cipher, http_client=http_client),
            local_fs_allowed_roots=settings.local_fs_allowed_roots,
        )
        app.state.ingest_jobs = IngestJobRepository(db, Uuid7Generator())
        yield test_client


def bearer(
    codec: PlatformTokenCodec, *, user: UserId, org: OrgId, session: SessionId
) -> dict[str, str]:
    token, _ = codec.mint(subject=user, org_id=org, session_id=session)
    return {"Authorization": f"Bearer {token}"}


def _headers_a(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_a, org=seeded.org_a, session=seeded.session_a)


def _headers_b(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_b, org=seeded.org_b, session=seeded.session_b)


def test_register_list_browse_and_ingest_a_local_fs_source(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, tmp_path: Path
) -> None:
    (tmp_path / "handbook.txt").write_text("leave policy")
    headers = _headers_a(codec, seeded)

    register = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={"slug": "fixtures", "name": "Fixtures", "kind": "local_fs", "root": str(tmp_path)},
    )
    assert register.status_code == 201, register.text
    assert register.json()["kind"] == "local_fs"

    listed = client.get("/api/v1/connectors", headers=headers)
    assert listed.status_code == 200
    assert [s["slug"] for s in listed.json()] == ["fixtures"]

    items = client.get("/api/v1/connectors/fixtures/items", headers=headers)
    assert items.status_code == 200
    assert [i["uri"] for i in items.json()] == ["handbook.txt"]

    ingest = client.post(
        "/api/v1/connectors/fixtures/ingest", headers=headers, json={"uri": "handbook.txt"}
    )
    assert ingest.status_code == 202, ingest.text
    body = ingest.json()
    assert body["status"] == "queued"
    assert body["uri"] == "handbook.txt"


def test_register_rejects_a_local_fs_root_outside_the_operator_approved_roots(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers_a(codec, seeded)

    response = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={"slug": "elsewhere", "name": "Elsewhere", "kind": "local_fs", "root": "/etc"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_register_the_same_slug_twice_is_a_conflict_not_a_500(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, tmp_path: Path
) -> None:
    headers = _headers_a(codec, seeded)
    body = {"slug": "dup", "name": "Dup", "kind": "local_fs", "root": str(tmp_path)}

    first = client.post("/api/v1/connectors", headers=headers, json=body)
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/connectors", headers=headers, json=body)
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "conflict"


def test_ingest_refuses_a_uri_the_source_does_not_currently_list(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, tmp_path: Path
) -> None:
    (tmp_path / "real.txt").write_text("hi")
    headers = _headers_a(codec, seeded)
    client.post(
        "/api/v1/connectors",
        headers=headers,
        json={"slug": "src", "name": "Src", "kind": "local_fs", "root": str(tmp_path)},
    )

    response = client.post(
        "/api/v1/connectors/src/ingest", headers=headers, json={"uri": "not-a-real-file.txt"}
    )

    assert response.status_code == 404, response.text


def test_org_b_cannot_list_or_browse_org_as_source(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, tmp_path: Path
) -> None:
    """The same cross-org isolation `test_knowledge_endpoints.py` proves for
    documents, proven here for `content_source`'s RLS policy (migration
    `0007`)."""
    headers_a = _headers_a(codec, seeded)
    headers_b = _headers_b(codec, seeded)
    client.post(
        "/api/v1/connectors",
        headers=headers_a,
        json={"slug": "private", "name": "Private", "kind": "local_fs", "root": str(tmp_path)},
    )

    listed_b = client.get("/api/v1/connectors", headers=headers_b)
    assert listed_b.status_code == 200
    assert listed_b.json() == []

    items_b = client.get("/api/v1/connectors/private/items", headers=headers_b)
    assert items_b.status_code == 404
