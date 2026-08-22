"""`C3` deliverable 1 — folders, on the wire.

Same shape as `test_chat_endpoints.py`: the real `create_app()`, the real
router, the real `SqlChatRepository`/`FolderService` against a real Postgres —
folder ownership and cross-tenant isolation are claims about row-level
security and an explicit `user_id` predicate, and a fake repository would only
prove the fake.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.entrypoints.api.main import create_app
from mnemos.features.chat.adapters.repository import SqlChatRepository
from mnemos.features.chat.application.folders import FolderService
from mnemos.features.chat.application.service import ChatService
from mnemos.features.identity.adapters.principals import SqlPrincipalRepository
from mnemos.features.identity.application.principals import PrincipalResolver
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

ORG_A_SLUG = "folders-org-a"
ORG_B_SLUG = "folders-org-b"


class Seed:
    def __init__(
        self,
        org_a: OrgId,
        user_a: UserId,
        session_a: SessionId,
        user_a2: UserId,
        session_a2: SessionId,
        org_b: OrgId,
        user_b: UserId,
        session_b: SessionId,
    ) -> None:
        self.org_a = org_a
        self.user_a = user_a
        self.session_a = session_a
        self.user_a2 = user_a2
        self.session_a2 = session_a2
        self.org_b = org_b
        self.user_b = user_b
        self.session_b = session_b


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    ids = Seed(
        org_a=OrgId(uuid7()),
        user_a=UserId(uuid7()),
        session_a=SessionId(uuid7()),
        user_a2=UserId(uuid7()),
        session_a2=SessionId(uuid7()),
        org_b=OrgId(uuid7()),
        user_b=UserId(uuid7()),
        session_b=SessionId(uuid7()),
    )
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)", ids.org_a, ORG_A_SLUG, ORG_A_SLUG
        )
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)", ids.org_b, ORG_B_SLUG, ORG_B_SLUG
        )
        for org_id, user_id, session_id, email in (
            (ids.org_a, ids.user_a, ids.session_a, "ada@folders.test"),
            (ids.org_a, ids.user_a2, ids.session_a2, "amir@folders.test"),
            (ids.org_b, ids.user_b, ids.session_b, "bob@folders.test"),
        ):
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
                f"hash-for-{email}",
                NOW + timedelta(days=14),
            )
        yield ids
        await conn.execute("DELETE FROM org WHERE id = ANY($1::uuid[])", [ids.org_a, ids.org_b])
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db(postgres: Postgres) -> AsyncIterator[Database]:
    database = Database(
        Settings(
            env="test",  # type: ignore[arg-type]
            database_url=postgres.app_url,
            app_database_password=APP_PASSWORD,  # type: ignore[arg-type]
        )
    )
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


def bearer(
    codec: PlatformTokenCodec, *, user: UserId, org: OrgId, session: SessionId
) -> dict[str, str]:
    token, _ = codec.mint(subject=user, org_id=org, session_id=session)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(codec: PlatformTokenCodec, clock: FrozenClock, db: Database) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(
            codec=codec, repository=SqlPrincipalRepository(db), clock=clock
        )
        chat_repository = SqlChatRepository(db, Uuid7Generator())
        app.state.chat_service = ChatService(
            repository=chat_repository, model=None, history_turns=12  # type: ignore[arg-type]
        )
        app.state.folder_service = FolderService(repository=chat_repository)
        yield test_client


def _headers(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_a, org=seeded.org_a, session=seeded.session_a)


# ------------------------------------------------------------------ folder CRUD


def test_create_list_rename_reorder_delete_a_folder(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)

    created = client.post("/api/v1/chat/folders", json={"name": "Q3 planning"}, headers=headers)
    assert created.status_code == 201
    folder_id = created.json()["id"]
    assert created.json()["name"] == "Q3 planning"
    assert created.json()["session_count"] == 0

    listed = client.get("/api/v1/chat/folders", headers=headers)
    assert listed.status_code == 200
    assert [f["id"] for f in listed.json()["folders"]] == [folder_id]

    renamed = client.patch(
        f"/api/v1/chat/folders/{folder_id}", json={"name": "Q4 planning"}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Q4 planning"

    reordered = client.patch(
        f"/api/v1/chat/folders/{folder_id}", json={"position": 5}, headers=headers
    )
    assert reordered.status_code == 200
    assert reordered.json()["position"] == 5
    # The name survives a position-only update — a partial update must not
    # clobber the fields it was not asked to touch.
    assert reordered.json()["name"] == "Q4 planning"

    deleted = client.delete(f"/api/v1/chat/folders/{folder_id}", headers=headers)
    assert deleted.status_code == 204

    after_delete = client.get("/api/v1/chat/folders", headers=headers)
    assert after_delete.json()["folders"] == []


def test_folders_with_tied_position_list_deterministically(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """Every new folder defaults to `position=0` until the caller reorders it,
    so an org with more than one un-reordered folder is exactly the tied-sort
    case TRACKER's 2026-08-22 notes describes fixing for `SqlToolRepository` —
    `list_folders` must order by `(position, id)`, not `position` alone, or
    two runs of this same test could observe a different order."""
    headers = _headers(codec, seeded)
    created_ids = [
        client.post("/api/v1/chat/folders", json={"name": f"folder-{i}"}, headers=headers).json()[
            "id"
        ]
        for i in range(5)
    ]

    first = [f["id"] for f in client.get("/api/v1/chat/folders", headers=headers).json()["folders"]]
    second = [f["id"] for f in client.get("/api/v1/chat/folders", headers=headers).json()["folders"]]

    assert first == second == created_ids


def test_a_session_can_be_moved_into_and_out_of_a_folder(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)
    folder_id = client.post(
        "/api/v1/chat/folders", json={"name": "Inbox"}, headers=headers
    ).json()["id"]
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]

    moved = client.patch(
        f"/api/v1/chat/sessions/{session_id}", json={"folder_id": folder_id}, headers=headers
    )
    assert moved.status_code == 200
    assert moved.json()["folder_id"] == folder_id

    in_folder = client.get("/api/v1/chat/folders", headers=headers).json()["folders"]
    assert next(f for f in in_folder if f["id"] == folder_id)["session_count"] == 1

    # Renaming the session must not silently un-file it — `folder_id` absent
    # from the body means "don't touch", not "clear" (TRACKER §5 deliverable 1).
    renamed = client.patch(
        f"/api/v1/chat/sessions/{session_id}", json={"title": "renamed"}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["folder_id"] == folder_id

    unfiled = client.patch(
        f"/api/v1/chat/sessions/{session_id}", json={"folder_id": None}, headers=headers
    )
    assert unfiled.status_code == 200
    assert unfiled.json()["folder_id"] is None


def test_deleting_a_folder_unfiles_its_sessions_without_deleting_them(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)
    folder_id = client.post(
        "/api/v1/chat/folders", json={"name": "Archive"}, headers=headers
    ).json()["id"]
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]
    client.patch(
        f"/api/v1/chat/sessions/{session_id}", json={"folder_id": folder_id}, headers=headers
    )

    deleted = client.delete(f"/api/v1/chat/folders/{folder_id}", headers=headers)
    assert deleted.status_code == 204

    fetched = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["session"]["folder_id"] is None


# ------------------------------------------------------------------ tenant / owner safety


def test_a_folder_from_another_org_is_not_readable(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    folder_id = client.post(
        "/api/v1/chat/folders", json={"name": "Org A only"}, headers=_headers(codec, seeded)
    ).json()["id"]

    org_b_headers = bearer(codec, user=seeded.user_b, org=seeded.org_b, session=seeded.session_b)
    response = client.patch(
        f"/api/v1/chat/folders/{folder_id}", json={"name": "hijacked"}, headers=org_b_headers
    )

    assert response.status_code == 404


def test_another_users_folder_in_the_same_org_is_a_404_and_not_a_403(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """Two users, same org — RLS alone cannot produce this 404; the service's
    `user_id` ownership check is what has to (mirrors
    `test_chat_endpoints.py::test_another_users_session_is_a_404_and_not_a_403`)."""
    folder_id = client.post(
        "/api/v1/chat/folders", json={"name": "Ada's folder"}, headers=_headers(codec, seeded)
    ).json()["id"]

    other_headers = bearer(
        codec, user=seeded.user_a2, org=seeded.org_a, session=seeded.session_a2
    )
    response = client.delete(f"/api/v1/chat/folders/{folder_id}", headers=other_headers)

    assert response.status_code == 404


def test_moving_a_session_into_another_users_folder_is_refused(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """A folder id from a different user in the same org must not silently
    file a session under it — even though the session itself belongs to the
    caller, the folder does not."""
    other_headers = bearer(
        codec, user=seeded.user_a2, org=seeded.org_a, session=seeded.session_a2
    )
    other_folder_id = client.post(
        "/api/v1/chat/folders", json={"name": "Amir's folder"}, headers=other_headers
    ).json()["id"]

    headers = _headers(codec, seeded)
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]
    response = client.patch(
        f"/api/v1/chat/sessions/{session_id}",
        json={"folder_id": other_folder_id},
        headers=headers,
    )

    assert response.status_code == 404
