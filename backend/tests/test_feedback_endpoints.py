"""`C3` deliverable 3 — feedback, on the wire.

Same shape as `test_bookmarks_endpoints.py`: the real `create_app()`, the real
router, the real `SqlChatRepository` against a real Postgres. Messages are
seeded directly via SQL rather than through the streaming endpoint.
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
from mnemos.features.chat.application.feedback import FeedbackService
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

ORG_A_SLUG = "feedback-org-a"
ORG_B_SLUG = "feedback-org-b"


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
            (ids.org_a, ids.user_a, ids.session_a, "ada@feedback.test"),
            (ids.org_a, ids.user_a2, ids.session_a2, "amir@feedback.test"),
            (ids.org_b, ids.user_b, ids.session_b, "bob@feedback.test"),
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
        app.state.feedback_service = FeedbackService(repository=chat_repository)
        yield test_client


def _headers(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_a, org=seeded.org_a, session=seeded.session_a)


def test_rate_a_message_up_then_switch_it_to_down_with_a_comment(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)

    up = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback", json={"rating": "up"}, headers=headers
    )
    assert up.status_code == 200
    assert up.json()["rating"] == "up"
    assert up.json()["comment"] is None

    down = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback",
        json={"rating": "down", "comment": "wrong region totals"},
        headers=headers,
    )
    assert down.status_code == 200
    assert down.json()["rating"] == "down"
    assert down.json()["comment"] == "wrong region totals"
    # Same row, not a second one.
    assert down.json()["id"] == up.json()["id"]


def test_the_session_detail_response_reflects_feedback_state(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)

    before = client.get(f"/api/v1/chat/sessions/{seeded.chat_session_a}", headers=headers)
    assert before.json()["messages"][0]["feedback"] is None

    client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback", json={"rating": "up"}, headers=headers
    )

    after = client.get(f"/api/v1/chat/sessions/{seeded.chat_session_a}", headers=headers)
    assert after.json()["messages"][0]["feedback"] == "up"


def test_removing_feedback_clears_it(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)
    client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback", json={"rating": "up"}, headers=headers
    )

    removed = client.delete(f"/api/v1/chat/messages/{seeded.message_a}/feedback", headers=headers)
    assert removed.status_code == 204

    after = client.get(f"/api/v1/chat/sessions/{seeded.chat_session_a}", headers=headers)
    assert after.json()["messages"][0]["feedback"] is None


def test_removing_feedback_that_does_not_exist_is_a_404(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    response = client.delete(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback", headers=_headers(codec, seeded)
    )
    assert response.status_code == 404


def test_rating_another_users_message_is_a_404_not_a_403(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """Same org, different user — RLS alone cannot produce this 404; the
    repository's join to `chat_session.user_id` has to."""
    other_headers = bearer(codec, user=seeded.user_a2, org=seeded.org_a, session=seeded.session_a2)
    response = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback",
        json={"rating": "up"},
        headers=other_headers,
    )
    assert response.status_code == 404


def test_rating_a_message_from_another_org_is_a_404(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    org_b_headers = bearer(codec, user=seeded.user_b, org=seeded.org_b, session=seeded.session_b)
    response = client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback",
        json={"rating": "up"},
        headers=org_b_headers,
    )
    assert response.status_code == 404


def test_feedback_from_one_user_is_invisible_on_another_users_view_of_the_message(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """Sessions are single-owner in this schema, so this asserts isolation
    the same way it matters elsewhere: a rating never leaks across users even
    when (hypothetically) reading the same message id directly."""
    headers = _headers(codec, seeded)
    client.put(
        f"/api/v1/chat/messages/{seeded.message_a}/feedback", json={"rating": "up"}, headers=headers
    )

    other_headers = bearer(codec, user=seeded.user_a2, org=seeded.org_a, session=seeded.session_a2)
    # user_a2 does not own chat_session_a, so even asking about it is a 404 —
    # confirms feedback state cannot be read through another user's session.
    response = client.get(f"/api/v1/chat/sessions/{seeded.chat_session_a}", headers=other_headers)
    assert response.status_code == 404
