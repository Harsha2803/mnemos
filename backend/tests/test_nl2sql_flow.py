"""`A3` deliverable 4 — `Nl2SqlFlow`, on the wire, against a real Postgres.

Same shape as `test_knowledge_endpoints.py`: the real `create_app()`, the real
router, real `mnemos_analytics` connected as the real `mnemos_ro` role — the
claims here (a rejected verdict never reaches the database, a repair attempt
records its own `sql_run` row, the persisted message links back to it) are
claims about the security invariant TRACKER §5 deliverable 4 exists to hold,
and a fake connection would only prove the fake honours it. Only the model is
scripted: nothing here needs a running Ollama.

**Every test function here is synchronous, not `@pytest.mark.asyncio`** — the
same discipline `test_chat_endpoints.py`/`test_knowledge_endpoints.py` use and
document. `TestClient` runs the ASGI app on its own thread and event loop
(an anyio "blocking portal"); a `Database`'s asyncpg pool binds to whichever
loop first checks a connection out of it, and reusing it from a second loop
raises `RuntimeError: ... attached to a different loop`. Any async work that
must happen outside the `TestClient` block — seeding, or a post-response
assertion the API has no endpoint for — goes through its own short-lived
`Database`/connection, built and disposed inside one `asyncio.run()` call, so
it never shares a bound engine with the one the request actually used.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import mnemos.platform.models  # noqa: F401
from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.crypto import DsnCipher
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.entrypoints.api.main import create_app
from mnemos.features.chat.adapters.repository import SqlChatRepository
from mnemos.features.chat.application.service import ChatService
from mnemos.features.datasources.adapters.executor import PostgresExecutor
from mnemos.features.datasources.adapters.introspection import PostgresIntrospector
from mnemos.features.datasources.adapters.models import SqlRun
from mnemos.features.datasources.adapters.repository import (
    DatasourceRepository,
    GlossaryRepository,
    SchemaObjectRepository,
    SqlRunRepository,
)
from mnemos.features.datasources.application.generation import SqlGenerationService
from mnemos.features.datasources.application.service import DatasourceService
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
from mnemos.flows.nl2sql.application import Nl2SqlFlow
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
DSN_KEY = "zqQeIteGh6YP2kybnsto8GE8W38N_u9yJhINMNKDpMg="
SLUG = "sales-warehouse"


class Seed:
    def __init__(self, org: OrgId, user: UserId, session: SessionId) -> None:
        self.org = org
        self.user = user
        self.session = session


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    ids = Seed(org=OrgId(uuid7()), user=UserId(uuid7()), session=SessionId(uuid7()))
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            ids.org,
            f"nl2sql-org-{ids.org.hex[:8]}",
            "NL2SQL Flow Test Org",
        )
        await conn.execute(
            "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
            ids.user,
            ids.org,
            "ada@nl2sql.test",
            "ada@nl2sql.test",
        )
        await conn.execute(
            "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
            "VALUES ($1, $2, $3, $4, $5)",
            ids.session,
            ids.org,
            ids.user,
            "hash-for-nl2sql-org",
            NOW + timedelta(days=14),
        )
        yield ids
        await conn.execute("DELETE FROM org WHERE id = $1", ids.org)
    finally:
        await conn.close()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def codec(clock: FrozenClock) -> PlatformTokenCodec:
    return PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER), clock=clock, ids=Uuid7Generator()
    )


class ScriptedModel:
    """`ChatModel` scripted for the NL2SQL flow: `.complete()` answers each
    successive generation attempt from a list (so a test can script "write,
    then a valid read" for the repair loop), `.stream()` answers narration
    with a fixed line. `complete_calls`/`stream_calls` record every turn
    sequence seen, the same reasoning `FakeChatModel` in `test_datasources_
    generation.py` gives for its own `calls` list.
    """

    def __init__(self, completions: Sequence[str], narration: str = "Here is your answer.") -> None:
        self._completions = list(completions)
        self._narration = narration
        self.complete_calls: list[list[ChatTurn]] = []
        self.stream_calls: list[list[ChatTurn]] = []

    @property
    def model_name(self) -> str:
        return "scripted-nl2sql-model"

    async def complete(self, messages: Sequence[ChatTurn]) -> ChatCompletion:
        self.complete_calls.append(list(messages))
        index = min(len(self.complete_calls) - 1, len(self._completions) - 1)
        return ChatCompletion(
            content=self._completions[index],
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=5,
        )

    async def stream(self, messages: Sequence[ChatTurn]) -> AsyncIterator[ChatStreamEvent]:
        self.stream_calls.append(list(messages))
        yield ChatToken(text=self._narration)
        yield ChatDone(finish_reason="stop", prompt_tokens=10, completion_tokens=5)

    async def health(self) -> None:
        return None


def _sql(text: str) -> str:
    return f"```sql\n{text}\n```"


def _fresh_database(postgres: Postgres) -> Database:
    """A `Database` that belongs to nobody else — used only for a single
    `asyncio.run()`-bounded call, built and disposed inside it, so it never
    shares a loop-bound engine with the one `TestClient`'s portal thread used
    for the actual request. See the module docstring."""
    return Database(
        Settings(
            env="test",  # type: ignore[arg-type]
            database_url=postgres.app_url,
            app_database_password=APP_PASSWORD,  # type: ignore[arg-type]
        )
    )


def register_datasource(postgres: Postgres, org_id: OrgId) -> None:
    """Registers and introspects the demo warehouse for `org_id`, entirely
    within one `asyncio.run()` call and its own throwaway `Database` — never
    the `db`/engine `TestClient` will use, and never touched from a second
    event loop afterward."""

    async def scenario() -> None:
        database = _fresh_database(postgres)
        try:
            ids = Uuid7Generator()
            service = DatasourceService(
                datasources=DatasourceRepository(database, ids),
                schema_objects=SchemaObjectRepository(database, ids),
                introspector=PostgresIntrospector(),
                cipher=DsnCipher(DSN_KEY),
                glossary=GlossaryRepository(database, ids),
                executor=PostgresExecutor(),
            )
            await service.register(
                org_id=org_id,
                slug=SLUG,
                name="Sales Warehouse",
                description="test",
                dsn=postgres.analytics_ro_url,
                read_only_role="mnemos_ro",
                allowed_schemas=["analytics"],
            )
            await service.refresh_schema(org_id=org_id, slug=SLUG)
        finally:
            await database.dispose()

    asyncio.run(scenario())


def sql_runs_for_org(postgres: Postgres, org_id: OrgId) -> list[tuple[int, str, uuid.UUID | None]]:
    """`(attempt, verdict, message_id)` for every `sql_run` row belonging to
    `org_id`, newest-attempt-last — read through a throwaway `Database`, the
    same reasoning `register_datasource` documents. There is no HTTP endpoint
    for this (TRACKER §5 does not ask for one), so this is the one place
    these tests reach past the API rather than through it.
    """

    async def scenario() -> list[tuple[int, str, uuid.UUID | None]]:
        database = _fresh_database(postgres)
        try:
            async with database.session(org_id=org_id) as session:
                rows = (
                    await session.scalars(
                        select(SqlRun).where(SqlRun.org_id == org_id).order_by(SqlRun.attempt)
                    )
                ).all()
                return [(r.attempt, r.verdict, r.message_id) for r in rows]
        finally:
            await database.dispose()

    return asyncio.run(scenario())


def sql_run_count_for_message(postgres: Postgres, org_id: OrgId, message_id: uuid.UUID) -> int:
    async def scenario() -> int:
        database = _fresh_database(postgres)
        try:
            async with database.session(org_id=org_id) as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(SqlRun)
                    .where(SqlRun.org_id == org_id, SqlRun.message_id == message_id)
                )
                return int(count or 0)
        finally:
            await database.dispose()

    return asyncio.run(scenario())


def region_row_count(postgres: Postgres) -> int:
    async def scenario() -> int:
        conn = await asyncpg.connect(postgres.analytics_owner_dsn)
        try:
            count = await conn.fetchval("SELECT count(*) FROM analytics.region")
            return int(count)
        finally:
            await conn.close()

    return asyncio.run(scenario())


def build_flow(
    postgres: Postgres, model: ScriptedModel, *, repair_attempts: int = 2, max_rows: int = 5_000
) -> Nl2SqlFlow:
    """A dedicated `Database` for the flow under test — built here, handed to
    `make_client`, and first actually used from inside `TestClient`'s portal
    loop when a request runs, which is what keeps it loop-consistent for the
    whole test.
    """
    database = _fresh_database(postgres)
    ids = Uuid7Generator()
    datasources = DatasourceService(
        datasources=DatasourceRepository(database, ids),
        schema_objects=SchemaObjectRepository(database, ids),
        introspector=PostgresIntrospector(),
        cipher=DsnCipher(DSN_KEY),
        glossary=GlossaryRepository(database, ids),
        executor=PostgresExecutor(),
    )
    generation = SqlGenerationService(
        datasources=datasources, model=model, sql_runs=SqlRunRepository(database, ids)
    )
    return Nl2SqlFlow(
        chat_repository=SqlChatRepository(database, ids),
        datasources=datasources,
        generation=generation,
        sql_runs=SqlRunRepository(database, ids),
        model=model,
        datasource_slug=SLUG,
        statement_timeout_ms=15_000,
        max_rows=max_rows,
        repair_attempts=repair_attempts,
    )


def make_client(
    codec: PlatformTokenCodec,
    clock: FrozenClock,
    postgres: Postgres,
    flow: Nl2SqlFlow,
    model: ScriptedModel,
) -> Iterator[TestClient]:
    """`app.state.rag_flow` is left exactly as the real `lifespan()` builds
    it — the NL2SQL-classified questions never call it, so the real (Ollama-backed)
    instance sitting unused is harmless. `app.state.db` (the real lifespan's
    own `Database`) points at whatever `get_settings()` resolves outside
    this test container, so `principals` *and* `chat_service` (session CRUD
    goes through it regardless of which flow later answers a message —
    `POST /sessions` never touches `nl2sql_flow`) need their own `Database`
    against `postgres` — built fresh here, first used only from inside this
    same `TestClient` block, for the same loop-consistency reason
    `build_flow`'s own `_fresh_database` call gives. `chat_service`'s own
    model is never exercised (only NL2SQL-classified requests are sent), so
    the same `model` the caller built `flow` with is reused
    rather than building a second, unused fake.
    """
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(
            codec=codec,
            repository=SqlPrincipalRepository(_fresh_database(postgres)),
            clock=clock,
        )
        app.state.chat_service = ChatService(
            repository=SqlChatRepository(_fresh_database(postgres), Uuid7Generator()),
            model=model,
            history_turns=12,
        )
        app.state.nl2sql_flow = flow
        yield test_client


def bearer(
    codec: PlatformTokenCodec, *, user: UserId, org: OrgId, session: SessionId
) -> dict[str, str]:
    token, _ = codec.mint(subject=user, org_id=org, session_id=session)
    return {"Authorization": f"Bearer {token}"}


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


def _create_session(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post("/api/v1/chat/sessions", json={}, headers=headers)
    assert created.status_code == 201
    result: str = created.json()["id"]
    return result


def _ask(
    client: TestClient, headers: dict[str, str], session_id: str, content: str
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": content},
        headers=headers,
    )
    assert response.status_code == 200
    frames = _parse_sse(response.content)
    [done] = [payload for name, payload in frames if name == "done"]
    return done


def test_execution_runs_the_allowed_statement_as_mnemos_ro_and_narrates_the_result(
    codec: PlatformTokenCodec, clock: FrozenClock, postgres: Postgres, seeded: Seed
) -> None:
    register_datasource(postgres, seeded.org)
    model = ScriptedModel([_sql("SELECT region_name FROM analytics.region")])
    flow = build_flow(postgres, model)

    for client in make_client(codec, clock, postgres, flow, model):
        headers = bearer(codec, user=seeded.user, org=seeded.org, session=seeded.session)
        session_id = _create_session(client, headers)

        done = _ask(client, headers, session_id, "which regions do we sell into?")

        nl2sql = done["nl2sql"]
        assert nl2sql["verdict"] == "allowed"
        assert nl2sql["executed"] is True
        assert nl2sql["row_count"] > 0
        assert nl2sql["columns"] == ["region_name"]
        assert len(nl2sql["rows"]) == nl2sql["row_count"]
        message = done["message"]
        assert message["flow"] == "nl2sql"
        assert message["content"] == "Here is your answer."


def test_a_rejected_verdict_is_never_executed(
    codec: PlatformTokenCodec, clock: FrozenClock, postgres: Postgres, seeded: Seed
) -> None:
    """The model complies with an adversarial question and writes a real
    `DELETE` on every attempt — the guard, not a repair, is what must hold."""
    register_datasource(postgres, seeded.org)
    count_before = region_row_count(postgres)

    model = ScriptedModel([_sql("DELETE FROM analytics.region")] * 3)
    flow = build_flow(postgres, model, repair_attempts=2)

    for client in make_client(codec, clock, postgres, flow, model):
        headers = bearer(codec, user=seeded.user, org=seeded.org, session=seeded.session)
        session_id = _create_session(client, headers)

        done = _ask(client, headers, session_id, "delete every region")

        nl2sql = done["nl2sql"]
        assert nl2sql["verdict"] == "rejected_write"
        assert nl2sql["executed"] is False
        assert nl2sql["row_count"] is None
        assert "region" in " ".join(nl2sql["denied_tables"])
        assert "refused" in done["message"]["content"].lower()
        assert done["message"]["router_rationale"] == ("Requests an operation on structured data.")
        assert model.stream_calls == [], "a rejected verdict must never reach the narration model"

    assert region_row_count(postgres) == count_before, "a rejected verdict reached the database"


def test_a_repaired_query_after_a_rejection_records_a_second_sql_run_row_at_attempt_two(
    codec: PlatformTokenCodec, clock: FrozenClock, postgres: Postgres, seeded: Seed
) -> None:
    register_datasource(postgres, seeded.org)
    model = ScriptedModel(
        [
            _sql("DELETE FROM analytics.region"),
            _sql("SELECT region_name FROM analytics.region"),
        ]
    )
    flow = build_flow(postgres, model, repair_attempts=2)

    for client in make_client(codec, clock, postgres, flow, model):
        headers = bearer(codec, user=seeded.user, org=seeded.org, session=seeded.session)
        session_id = _create_session(client, headers)

        done = _ask(client, headers, session_id, "which regions do we sell into?")

        nl2sql = done["nl2sql"]
        assert nl2sql["attempt"] == 2
        assert nl2sql["verdict"] == "allowed"
        assert nl2sql["executed"] is True

    rows = sql_runs_for_org(postgres, seeded.org)
    assert [attempt for attempt, _verdict, _message_id in rows] == [1, 2]
    assert rows[0][1] == "rejected_write"
    assert rows[1][1] == "allowed"


def test_the_persisted_assistant_message_carries_flow_nl2sql_and_the_sql_run_id(
    codec: PlatformTokenCodec, clock: FrozenClock, postgres: Postgres, seeded: Seed
) -> None:
    register_datasource(postgres, seeded.org)
    model = ScriptedModel([_sql("SELECT region_name FROM analytics.region")])
    flow = build_flow(postgres, model)

    message_id: uuid.UUID | None = None
    for client in make_client(codec, clock, postgres, flow, model):
        headers = bearer(codec, user=seeded.user, org=seeded.org, session=seeded.session)
        session_id = _create_session(client, headers)
        done = _ask(client, headers, session_id, "which regions do we sell into?")
        message_id = uuid.UUID(str(done["message"]["id"]))

    assert message_id is not None
    assert sql_run_count_for_message(postgres, seeded.org, message_id) == 1
