"""`C3` deliverable 4 — history search, on the wire.

Same shape as `test_bookmarks_endpoints.py`: the real `create_app()`, the
real router, real Postgres — full-text ranking and RLS scoping are both
claims a fake repository could not prove. Sessions and messages are seeded
directly via SQL.
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

ORG_A_SLUG = "search-org-a"
ORG_B_SLUG = "search-org-b"


class Seed:
    def __init__(
        self,
        org_a: OrgId,
        user_a: UserId,
        session_a: SessionId,
        title_hit_session: str,
        content_hit_session: str,
        no_match_session: str,
        org_b: OrgId,
        user_b: UserId,
        session_b: SessionId,
        other_org_session: str,
    ) -> None:
        self.org_a = org_a
        self.user_a = user_a
        self.session_a = session_a
        self.title_hit_session = title_hit_session
        self.content_hit_session = content_hit_session
        self.no_match_session = no_match_session
        self.org_b = org_b
        self.user_b = user_b
        self.session_b = session_b
        self.other_org_session = other_org_session


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    ids = Seed(
        org_a=OrgId(uuid7()),
        user_a=UserId(uuid7()),
        session_a=SessionId(uuid7()),
        title_hit_session=str(uuid7()),
        content_hit_session=str(uuid7()),
        no_match_session=str(uuid7()),
        org_b=OrgId(uuid7()),
        user_b=UserId(uuid7()),
        session_b=SessionId(uuid7()),
        other_org_session=str(uuid7()),
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
            (ids.org_a, ids.user_a, ids.session_a, "ada@search.test"),
            (ids.org_b, ids.user_b, ids.session_b, "bob@search.test"),
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
        for session_id, org_id, user_id, title in (
            (ids.title_hit_session, ids.org_a, ids.user_a, "Quarterly leave policy"),
            (ids.content_hit_session, ids.org_a, ids.user_a, "New chat"),
            (ids.no_match_session, ids.org_a, ids.user_a, "New chat"),
            (ids.other_org_session, ids.org_b, ids.user_b, "New chat"),
        ):
            await conn.execute(
                "INSERT INTO chat_session (id, org_id, user_id, title) VALUES ($1, $2, $3, $4)",
                session_id,
                org_id,
                user_id,
                title,
            )
        for session_id, org_id, content in (
            (ids.title_hit_session, ids.org_a, "Ask HR for the leave form."),
            (
                ids.content_hit_session,
                ids.org_a,
                "Carry-over of unused leave is capped at five days.",
            ),
            (ids.no_match_session, ids.org_a, "The weather today is sunny."),
            (
                ids.other_org_session,
                ids.org_b,
                "Unused leave carries over up to five days here too.",
            ),
        ):
            await conn.execute(
                "INSERT INTO chat_message (id, org_id, session_id, ordinal, role, content) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                uuid7(),
                org_id,
                session_id,
                0,
                "assistant",
                content,
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
        yield test_client


def _headers(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_a, org=seeded.org_a, session=seeded.session_a)


def test_a_session_is_found_by_message_content_it_does_not_title_match(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    response = client.get(
        "/api/v1/chat/sessions",
        params={"q": "carry-over unused leave"},
        headers=_headers(codec, seeded),
    )
    assert response.status_code == 200
    ids = [s["id"] for s in response.json()["sessions"]]
    assert seeded.content_hit_session in ids
    hit = next(s for s in response.json()["sessions"] if s["id"] == seeded.content_hit_session)
    assert hit["snippet"] is not None
    assert "leave" in hit["snippet"].lower()
    # `ts_headline` wraps its matches in `<b>...</b>` by default — the
    # frontend renders this as plain text, so raw markup reaching the wire
    # would show up as literal "<b>" in the UI, not bold text.
    assert "<b>" not in hit["snippet"]
    assert "</b>" not in hit["snippet"]


def test_a_session_title_match_ranks_above_a_content_only_match(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    response = client.get(
        "/api/v1/chat/sessions", params={"q": "leave"}, headers=_headers(codec, seeded)
    )
    assert response.status_code == 200
    ids = [s["id"] for s in response.json()["sessions"]]
    assert ids.index(seeded.title_hit_session) < ids.index(seeded.content_hit_session)
    # The title match has no snippet — it matched on its own name, not a
    # passage inside it.
    title_hit = next(s for s in response.json()["sessions"] if s["id"] == seeded.title_hit_session)
    assert title_hit["snippet"] is None


def test_search_does_not_return_a_session_with_no_match(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    response = client.get(
        "/api/v1/chat/sessions", params={"q": "leave"}, headers=_headers(codec, seeded)
    )
    ids = [s["id"] for s in response.json()["sessions"]]
    assert seeded.no_match_session not in ids


def test_search_never_returns_another_orgs_matching_session(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    response = client.get(
        "/api/v1/chat/sessions", params={"q": "leave"}, headers=_headers(codec, seeded)
    )
    ids = [s["id"] for s in response.json()["sessions"]]
    assert seeded.other_org_session not in ids


def test_a_blank_query_falls_back_to_ordinary_recency_listing(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    blank = client.get(
        "/api/v1/chat/sessions", params={"q": "   "}, headers=_headers(codec, seeded)
    )
    unqualified = client.get("/api/v1/chat/sessions", headers=_headers(codec, seeded))
    assert [s["id"] for s in blank.json()["sessions"]] == [
        s["id"] for s in unqualified.json()["sessions"]
    ]
