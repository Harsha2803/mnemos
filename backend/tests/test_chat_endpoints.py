"""`A1` — chat sessions, messages, and the SSE streaming endpoint, on the wire.

Same shape as `test_principal_repository.py`: the real `create_app()`, the real
router, the real `SqlChatRepository` against a **real** Postgres — because
`test_a_chat_session_from_another_org_is_not_readable` is a claim about row-level
security, and a fake would only prove the fake. Only the model is faked: nothing
here should need a running Ollama, and `test_llm_gateway.py` already covers the
adapter that talks to one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.errors import UpstreamError
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.entrypoints.api.main import create_app
from mnemos.entrypoints.api.security import public_route_paths
from mnemos.features.chat.adapters.repository import SqlChatRepository
from mnemos.features.chat.application.service import ChatService
from mnemos.features.identity.adapters.principals import SqlPrincipalRepository
from mnemos.features.identity.application.principals import PrincipalResolver
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.features.llm.domain.model import (
    ChatCompletion,
    ChatDone,
    ChatStreamEvent,
    ChatToken,
    ChatTurn,
)
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

ORG_A_SLUG = "chat-org-a"
ORG_B_SLUG = "chat-org-b"


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
            (ids.org_a, ORG_A_SLUG, ids.user_a, ids.session_a, "ada@chat.test"),
            (ids.org_b, ORG_B_SLUG, ids.user_b, ids.session_b, "bob@chat.test"),
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


class FakeChatModel:
    """`ChatModel` that plays back a scripted list of events, or raises.

    `calls` records every turn sequence it was asked to answer, which is what
    lets a test assert the system prompt and history were assembled correctly
    without depending on Ollama's wire format at all.
    """

    #: What the client is allowed to see for either failure mode — a
    #: constant, exactly like `OllamaChatModel` raises. The sensitive text
    #: lives in `details`, which `MnemosError.expose_details=False` keeps off
    #: the wire; a test that put it in `message` would be asserting a
    #: property the real adapter does not have.
    PUBLIC_MESSAGE = "the model is unavailable"
    SECRET_DETAIL = "internal reason: dsn=postgresql://leak-me-not"

    def __init__(
        self,
        events: Sequence[ChatStreamEvent] | None = None,
        *,
        fail_immediately: bool = False,
        fail_after_events: bool = False,
    ) -> None:
        self._events = list(
            events
            if events is not None
            else [
                ChatToken(text="hi"),
                ChatDone(finish_reason="stop", prompt_tokens=1, completion_tokens=1),
            ]
        )
        self._fail_immediately = fail_immediately
        self._fail_after_events = fail_after_events
        self.calls: list[list[ChatTurn]] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def stream(self, messages: Sequence[ChatTurn]) -> AsyncIterator[ChatStreamEvent]:
        self.calls.append(list(messages))
        if self._fail_immediately:
            raise UpstreamError(self.PUBLIC_MESSAGE, reason=self.SECRET_DETAIL)
        for event in self._events:
            yield event
        if self._fail_after_events:
            raise UpstreamError(self.PUBLIC_MESSAGE, reason=self.SECRET_DETAIL)

    async def complete(self, messages: Sequence[ChatTurn]) -> ChatCompletion:
        return ChatCompletion(
            content="unused", finish_reason="stop", prompt_tokens=0, completion_tokens=0
        )

    async def health(self) -> None:
        return None


def bearer(
    codec: PlatformTokenCodec, *, user: UserId, org: OrgId, session: SessionId
) -> dict[str, str]:
    token, _ = codec.mint(subject=user, org_id=org, session_id=session)
    return {"Authorization": f"Bearer {token}"}


def make_client(
    codec: PlatformTokenCodec, clock: FrozenClock, db: Database, model: FakeChatModel
) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(
            codec=codec, repository=SqlPrincipalRepository(db), clock=clock
        )
        app.state.chat_service = ChatService(
            repository=SqlChatRepository(db, Uuid7Generator()), model=model, history_turns=12
        )
        yield test_client


@pytest.fixture
def model() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def client(
    codec: PlatformTokenCodec, clock: FrozenClock, db: Database, model: FakeChatModel
) -> Iterator[TestClient]:
    yield from make_client(codec, clock, db, model)


def _headers(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_a, org=seeded.org_a, session=seeded.session_a)


def _parse_sse(raw: bytes) -> list[tuple[str, dict[str, object]]]:
    frames: list[tuple[str, dict[str, object]]] = []
    for block in raw.decode().split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        name = event_line.removeprefix("event: ")
        payload = json.loads(data_line.removeprefix("data: "))
        frames.append((name, payload))
    return frames


# ------------------------------------------------------------------ session CRUD


def test_create_list_get_rename_delete_a_session(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)

    created = client.post("/api/v1/chat/sessions", json={}, headers=headers)
    assert created.status_code == 201
    session_id = created.json()["id"]
    assert created.json()["title"] == "New chat"

    listed = client.get("/api/v1/chat/sessions", headers=headers)
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()["sessions"]] == [session_id]

    fetched = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["session"]["id"] == session_id
    assert fetched.json()["messages"] == []

    renamed = client.patch(
        f"/api/v1/chat/sessions/{session_id}", json={"title": "Q3 planning"}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Q3 planning"

    deleted = client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 204

    after_delete = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert after_delete.status_code == 404


def test_sessions_are_listed_newest_first(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)
    first = client.post("/api/v1/chat/sessions", json={"title": "first"}, headers=headers).json()
    second = client.post("/api/v1/chat/sessions", json={"title": "second"}, headers=headers).json()

    listed = client.get("/api/v1/chat/sessions", headers=headers).json()

    assert [s["id"] for s in listed["sessions"]] == [second["id"], first["id"]]


# ------------------------------------------------------------------ tenant / owner safety


def test_a_chat_session_from_another_org_is_not_readable(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """A claim about row-level security: the session is created under org A's
    scoped connection, and org B's token can never make `app.current_org` name
    org A, so the read finds nothing — not a permission the application had to
    remember to check."""
    created = client.post("/api/v1/chat/sessions", json={}, headers=_headers(codec, seeded)).json()

    org_b_headers = bearer(codec, user=seeded.user_b, org=seeded.org_b, session=seeded.session_b)
    response = client.get(f"/api/v1/chat/sessions/{created['id']}", headers=org_b_headers)

    assert response.status_code == 404


def test_another_users_session_is_a_404_and_not_a_403(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, postgres: Postgres
) -> None:
    """Two users, same org this time — so RLS alone cannot produce the 404;
    the service's ownership check is what has to."""
    other_user = uuid7()
    other_session = uuid7()

    async def _seed_second_user() -> None:
        c = await asyncpg.connect(postgres.owner_dsn)
        try:
            await c.execute(
                "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
                other_user,
                seeded.org_a,
                "carol@chat.test",
                "carol@chat.test",
            )
            await c.execute(
                "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
                "VALUES ($1, $2, $3, $4, $5)",
                other_session,
                seeded.org_a,
                other_user,
                "hash-for-carol",
                NOW + timedelta(days=14),
            )
        finally:
            await c.close()

    asyncio.run(_seed_second_user())

    created = client.post("/api/v1/chat/sessions", json={}, headers=_headers(codec, seeded)).json()
    carol_headers = bearer(
        codec, user=UserId(other_user), org=seeded.org_a, session=SessionId(other_session)
    )

    response = client.get(f"/api/v1/chat/sessions/{created['id']}", headers=carol_headers)

    assert response.status_code == 404


def test_the_chat_routes_are_authenticated_by_default(client: TestClient) -> None:
    """Extends the `A0` guard's claim (`test_route_guard.py`) onto the new
    surface: nothing here was added to `public_route_paths`."""
    paths = public_route_paths("/api/v1")
    assert not any(p.startswith("/api/v1/chat") for p in paths)

    assert client.post("/api/v1/chat/sessions", json={}).status_code == 401
    assert client.get("/api/v1/chat/sessions").status_code == 401


# ------------------------------------------------------------------ streaming


def test_a_message_streams_token_by_token_and_the_answer_is_persisted(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, model: FakeChatModel
) -> None:
    """Asserts the **SSE frames on the wire** — named events, not bare data
    lines — rather than the generator, per the M3.2a lesson (a control tested
    one layer below where it takes effect is not tested)."""
    headers = _headers(codec, seeded)
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]

    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "hello there"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = b"".join(response.iter_bytes())

    frames = _parse_sse(raw)
    names = [name for name, _ in frames]
    assert names == ["token", "done"]
    assert frames[0][1] == {"text": "hi"}
    assert frames[1][0] == "done"
    assert frames[1][1]["message"]["role"] == "assistant"
    assert frames[1][1]["message"]["content"] == "hi"

    detail = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()
    roles = [m["role"] for m in detail["messages"]]
    contents = [m["content"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert contents == ["hello there", "hi"]

    # The system prompt plus the user's turn is what the model actually saw.
    assert len(model.calls) == 1
    assert model.calls[0][0].role.value == "system"
    assert model.calls[0][-1].content == "hello there"


def test_sending_a_message_to_a_missing_session_is_a_404_before_any_bytes_stream(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    missing = uuid7()
    response = client.post(
        f"/api/v1/chat/sessions/{missing}/messages",
        json={"content": "hello"},
        headers=_headers(codec, seeded),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_an_ollama_failure_before_any_token_becomes_a_502_and_leaks_no_upstream_text(
    codec: PlatformTokenCodec, clock: FrozenClock, db: Database, seeded: Seed
) -> None:
    failing_model = FakeChatModel(fail_immediately=True)
    client_iter = make_client(codec, clock, db, failing_model)
    client = next(client_iter)
    try:
        headers = _headers(codec, seeded)
        session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]

        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"content": "hello"},
            headers=headers,
        )

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "upstream_error"
        assert body["error"]["message"] == FakeChatModel.PUBLIC_MESSAGE
        assert FakeChatModel.SECRET_DETAIL not in json.dumps(body)
    finally:
        with pytest.raises(StopIteration):
            next(client_iter)


def test_an_ollama_failure_mid_stream_becomes_an_error_frame_not_a_crash(
    codec: PlatformTokenCodec, clock: FrozenClock, db: Database, seeded: Seed
) -> None:
    """Tokens already sent means the response already committed to 200 — the
    only honest way to report the failure is inside the stream."""
    flaky_model = FakeChatModel(
        events=[ChatToken(text="par"), ChatToken(text="tial")], fail_after_events=True
    )
    client_iter = make_client(codec, clock, db, flaky_model)
    client = next(client_iter)
    try:
        headers = _headers(codec, seeded)
        session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]

        with client.stream(
            "POST",
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"content": "hello"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes())

        frames = _parse_sse(raw)
        assert [name for name, _ in frames] == ["token", "token", "error"]
        assert frames[2][1] == {"message": "the model is unavailable right now"}
        assert FakeChatModel.SECRET_DETAIL not in json.dumps(frames)

        detail = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()
        roles = [m["role"] for m in detail["messages"]]
        # The user's question is there; no half-written assistant answer is.
        assert roles == ["user"]
    finally:
        with pytest.raises(StopIteration):
            next(client_iter)


def test_an_abandoned_stream_leaves_no_half_written_assistant_message(
    codec: PlatformTokenCodec, clock: FrozenClock, db: Database, seeded: Seed
) -> None:
    """Drives `ChatService.stream_reply` directly and closes it early —
    simulating the cancellation Starlette performs on a real client
    disconnect, which `TestClient`'s in-process transport cannot reliably
    reproduce. The mechanism under test (persistence deferred until the loop
    reaches `ChatDone`, per the module docstring) is exercised either way;
    what is not exercised here is Starlette's own disconnect wiring, which is
    framework behaviour rather than this milestone's code.
    """
    model = FakeChatModel(
        events=[ChatToken(text="par"), ChatToken(text="tial"), ChatToken(text="!!")]
    )
    repository = SqlChatRepository(db, Uuid7Generator())
    service = ChatService(repository=repository, model=model, history_turns=12)

    # One `asyncio.run()` for the whole test, not three: `db`'s asyncpg
    # connections are bound to whichever loop first uses them, and a second
    # `asyncio.run()` call hands the pool a brand new loop it cannot use.
    async def _create_drive_and_check() -> list[str]:
        session = await repository.create_session(
            org_id=seeded.org_a, user_id=seeded.user_a, title="abandon me"
        )
        gen = service.stream_reply(
            org_id=seeded.org_a,
            user_id=seeded.user_a,
            session_id=session.id,
            content="hello",
        )
        first = await gen.__anext__()
        assert first.text == "par"  # type: ignore[union-attr]
        await gen.aclose()

        messages = await repository.list_messages(org_id=seeded.org_a, session_id=session.id)
        return [m.role.value for m in messages]

    roles = asyncio.run(_create_drive_and_check())
    assert roles == ["user"]
