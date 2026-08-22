"""`C3` deliverable 2 — bookmarks, on the wire.

Same shape as `test_folders_endpoints.py`: the real `create_app()`, the real
router, the real `SqlChatRepository` against a real Postgres. Messages are
seeded directly via SQL rather than through the streaming endpoint — bookmark
ownership and the join-back-to-session shape are what these tests are about,
not the LLM round trip `test_chat_endpoints.py` already covers.
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
from mnemos.features.chat.application.bookmarks import BookmarkService
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

ORG_A_SLUG = "bookmarks-org-a"
ORG_B_SLUG = "bookmarks-org-b"


class Seed:
    def __init__(
        self,
        org_a: OrgId,
        user_a: UserId,
        session_a: SessionId,
        chat_session_a: str,
        message_a: str,
        user_a2: UserId,
        session_a2: SessionId,
        org_b: OrgId,
        user_b: UserId,
        session_b: SessionId,
    ) -> None:
        self.org_a = org_a
        self.user_a = user_a
        self.session_a = session_a
        self.chat_session_a = chat_session_a
        self.message_a = message_a
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
        chat_session_a=str(uuid7()),
        message_a=str(uuid7()),
        user_a2=UserId(uuid7()),
        session_a2=SessionId(uuid7()),
        org_b=OrgId(uuid7()),
        user_b=UserId(uuid7()),
        session_b=SessionId(uuid7()),
    )
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            ids.org_a,
            ORG_A_SLUG,
            ORG_A_SLUG,
        )
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            ids.org_b,
            ORG_B_SLUG,
            ORG_B_SLUG,
        )
        for org_id, user_id, session_id, email in (
            (ids.org_a, ids.user_a, ids.session_a, "ada@bookmarks.test"),
            (ids.org_a, ids.user_a2, ids.session_a2, "amir@bookmarks.test"),
            (ids.org_b, ids.user_b, ids.session_b, "bob@bookmarks.test"),
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
        await conn.execute(
            "INSERT INTO chat_session (id, org_id, user_id, title) VALUES ($1, $2, $3, $4)",
            ids.chat_session_a,
            ids.org_a,
            ids.user_a,
            "A conversation",
        )
        await conn.execute(
            "INSERT INTO chat_message (id, org_id, session_id, ordinal, role, content) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            ids.message_a,
            ids.org_a,
            ids.chat_session_a,
            0,
            "assistant",
            "Paris is the capital of France.",
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
            repository=chat_repository,
            model=None,
            history_turns=12,  # type: ignore[arg-type]
        )
        app.state.bookmark_service = BookmarkService(repository=chat_repository)
        yield test_client


def _headers(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_a, org=seeded.org_a, session=seeded.session_a)


def test_bookmark_a_message_with_a_note_then_list_and_remove_it(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)

    created = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/bookmark",
        json={"note": "good phrasing to reuse"},
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["message_id"] == seeded.message_a
    assert created.json()["note"] == "good phrasing to reuse"

    listed = client.get("/api/v1/chat/bookmarks", headers=headers)
    assert listed.status_code == 200
    [item] = listed.json()["bookmarks"]
    assert item["message_id"] == seeded.message_a
    assert item["session_id"] == seeded.chat_session_a
    assert item["session_title"] == "A conversation"
    assert item["message_content"] == "Paris is the capital of France."
    assert item["note"] == "good phrasing to reuse"

    removed = client.delete(f"/api/v1/chat/messages/{seeded.message_a}/bookmark", headers=headers)
    assert removed.status_code == 204

    after_removal = client.get("/api/v1/chat/bookmarks", headers=headers)
    assert after_removal.json()["bookmarks"] == []


def test_bookmarking_the_same_message_twice_updates_the_note_not_a_new_row(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)

    first = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/bookmark", json={"note": "v1"}, headers=headers
    )
    second = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/bookmark", json={"note": "v2"}, headers=headers
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listed = client.get("/api/v1/chat/bookmarks", headers=headers).json()["bookmarks"]
    assert len(listed) == 1
    assert listed[0]["note"] == "v2"


def test_the_session_detail_response_reflects_bookmark_state(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)

    before = client.get(f"/api/v1/chat/sessions/{seeded.chat_session_a}", headers=headers)
    assert before.json()["messages"][0]["bookmarked"] is False

    client.put(f"/api/v1/chat/messages/{seeded.message_a}/bookmark", json={}, headers=headers)

    after = client.get(f"/api/v1/chat/sessions/{seeded.chat_session_a}", headers=headers)
    assert after.json()["messages"][0]["bookmarked"] is True


def test_removing_a_bookmark_that_does_not_exist_is_a_404(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    response = client.delete(
        f"/api/v1/chat/messages/{seeded.message_a}/bookmark", headers=_headers(codec, seeded)
    )
    assert response.status_code == 404


def test_bookmarking_another_users_message_is_a_404_not_a_403(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """Same org, different user — RLS alone cannot produce this 404; the
    repository's join to `chat_session.user_id` has to."""
    other_headers = bearer(codec, user=seeded.user_a2, org=seeded.org_a, session=seeded.session_a2)
    response = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/bookmark", json={}, headers=other_headers
    )
    assert response.status_code == 404


def test_bookmarking_a_message_from_another_org_is_a_404(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    org_b_headers = bearer(codec, user=seeded.user_b, org=seeded.org_b, session=seeded.session_b)
    response = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/bookmark", json={}, headers=org_b_headers
    )
    assert response.status_code == 404


def test_a_bookmark_from_one_user_is_invisible_to_another_user_in_the_same_org(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)
    client.put(f"/api/v1/chat/messages/{seeded.message_a}/bookmark", json={}, headers=headers)

    other_headers = bearer(codec, user=seeded.user_a2, org=seeded.org_a, session=seeded.session_a2)
    listed = client.get("/api/v1/chat/bookmarks", headers=other_headers)
    assert listed.json()["bookmarks"] == []
