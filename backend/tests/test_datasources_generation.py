"""`A3` deliverable 3 — generation and the AST guard, wired together against a
real Postgres and a scripted model.

The claims here are about the *second* defence and about the audit trail: an
attempt is recorded whether it is allowed or refused, a datasource belonging
to another org is indistinguishable from a nonexistent one, and — the one
that does not touch `SqlGenerationService` at all —`mnemos_ro` really cannot
write even if this module's guard somehow let something through. A fake
repository or a fake role would only prove the fake behaves; `test_
datasources_glossary.py` and `test_datasources_introspection.py` make the
same argument about their own deliverables.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import asyncpg
import pytest
import pytest_asyncio

import mnemos.platform.models  # noqa: F401
from mnemos.core.crypto import DsnCipher
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.core.types import SqlVerdict
from mnemos.features.datasources.adapters.executor import PostgresExecutor
from mnemos.features.datasources.adapters.introspection import PostgresIntrospector
from mnemos.features.datasources.adapters.repository import (
    DatasourceRepository,
    GlossaryRepository,
    SchemaObjectRepository,
    SqlRunRepository,
)
from mnemos.features.datasources.application.generation import SqlGenerationService
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.datasources.domain import extract_sql_statement
from mnemos.features.identity.domain import OrgId
from mnemos.features.llm.domain.model import ChatCompletion, ChatTurn
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

DSN_KEY = "zqQeIteGh6YP2kybnsto8GE8W38N_u9yJhINMNKDpMg="
SLUG = "sales-warehouse"


class FakeChatModel:
    """`ChatModel` that returns one scripted completion. `calls` records
    every turn sequence it was asked to answer, so a test can assert the
    schema context and question were assembled into the prompt without
    depending on Ollama's wire format at all — the same reasoning behind
    `test_chat_endpoints.py`'s own `FakeChatModel`."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[list[ChatTurn]] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def stream(self, messages: Sequence[ChatTurn]) -> AsyncIterator[object]:
        raise NotImplementedError("SqlGenerationService uses complete(), never stream()")
        yield  # pragma: no cover - unreachable, satisfies the AsyncIterator shape

    async def complete(self, messages: Sequence[ChatTurn]) -> ChatCompletion:
        self.calls.append(list(messages))
        return ChatCompletion(
            content=self._content, finish_reason="stop", prompt_tokens=1, completion_tokens=1
        )

    async def health(self) -> None:
        return None


@pytest_asyncio.fixture
async def org_id(postgres: Postgres) -> AsyncIterator[OrgId]:
    new_org = OrgId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            new_org,
            f"ds-generation-org-{new_org.hex[:8]}",
            "Datasource Generation Test Org",
        )
        yield new_org
        await conn.execute("DELETE FROM org WHERE id = $1", new_org)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def other_org_id(postgres: Postgres) -> AsyncIterator[OrgId]:
    """A second, distinct org — for the one test that must prove a datasource
    registered to `org_id` is invisible from here, not merely "not found"."""
    new_org = OrgId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            new_org,
            f"ds-generation-other-org-{new_org.hex[:8]}",
            "Datasource Generation Other Org",
        )
        yield new_org
        await conn.execute("DELETE FROM org WHERE id = $1", new_org)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db(postgres: Postgres) -> AsyncIterator[Database]:
    from mnemos.core.config import Settings

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
def datasource_service(db: Database) -> DatasourceService:
    ids = Uuid7Generator()
    return DatasourceService(
        datasources=DatasourceRepository(db, ids),
        schema_objects=SchemaObjectRepository(db, ids),
        introspector=PostgresIntrospector(),
        cipher=DsnCipher(DSN_KEY),
        glossary=GlossaryRepository(db, ids),
        executor=PostgresExecutor(),
    )


@pytest_asyncio.fixture
async def registered(
    datasource_service: DatasourceService, postgres: Postgres, org_id: OrgId
) -> None:
    await datasource_service.register(
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )
    await datasource_service.refresh_schema(org_id=org_id, slug=SLUG)


def _service(
    datasource_service: DatasourceService, db: Database, model: FakeChatModel
) -> SqlGenerationService:
    return SqlGenerationService(
        datasources=datasource_service, model=model, sql_runs=SqlRunRepository(db, Uuid7Generator())
    )


# --------------------------------------------------------------------------
# extract_sql_statement: pure, no fixtures
# --------------------------------------------------------------------------


def test_extract_sql_statement_pulls_the_fenced_block() -> None:
    response = "Here you go:\n```sql\nSELECT * FROM analytics.customer\n```\nLet me know!"
    assert extract_sql_statement(response) == "SELECT * FROM analytics.customer"


def test_extract_sql_statement_accepts_a_fence_with_no_language_tag() -> None:
    response = "```\nSELECT * FROM analytics.region\n```"
    assert extract_sql_statement(response) == "SELECT * FROM analytics.region"


def test_extract_sql_statement_falls_back_to_the_whole_response_when_unfenced() -> None:
    """A small model does not always follow the fence instruction. Extraction
    does not need to be clever here — `guard_sql`'s parse step is what
    actually decides whether the fallback text was usable SQL."""
    assert extract_sql_statement("SELECT * FROM analytics.region") == (
        "SELECT * FROM analytics.region"
    )


def test_extract_sql_statement_strips_trailing_semicolon_and_whitespace() -> None:
    response = "```sql\n  SELECT 1;  \n```"
    assert extract_sql_statement(response) == "SELECT 1"


# --------------------------------------------------------------------------
# SqlGenerationService.generate: against a real Postgres
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_records_an_allowed_verdict_with_the_tables_it_touched(
    datasource_service: DatasourceService, db: Database, org_id: OrgId, registered: None
) -> None:
    model = FakeChatModel("```sql\nSELECT customer_id FROM analytics.customer\n```")
    service = _service(datasource_service, db, model)

    run = await service.generate(org_id=org_id, slug=SLUG, question="which customers exist?")

    assert run.verdict == SqlVerdict.ALLOWED
    assert run.verdict_detail is None
    assert run.generated_sql == "SELECT customer_id FROM analytics.customer"
    assert run.authorized_tables == ["analytics.customer"]
    assert run.denied_tables == []
    assert run.question == "which customers exist?"
    assert run.attempt == 1

    # The rendered schema+glossary context reached the model as a system
    # turn, and the question as the user turn — not lost, not reordered.
    [turns] = model.calls
    assert turns[-1].content == "which customers exist?"
    assert any("analytics.customer" in t.content for t in turns[:-1])


@pytest.mark.asyncio
async def test_every_attempt_writes_a_sql_run_row_with_its_verdict(
    datasource_service: DatasourceService, db: Database, org_id: OrgId, registered: None
) -> None:
    """An audit trail that only records successes is not one — the guard
    refusing a write must be exactly as durable as it allowing a read."""
    from sqlalchemy import func, select

    from mnemos.features.datasources.adapters.models import SqlRun

    allowed_model = FakeChatModel("```sql\nSELECT customer_id FROM analytics.customer\n```")
    allowed_run = await _service(datasource_service, db, allowed_model).generate(
        org_id=org_id, slug=SLUG, question="which customers exist?"
    )

    rejected_model = FakeChatModel("```sql\nDELETE FROM analytics.region\n```")
    rejected_run = await _service(datasource_service, db, rejected_model).generate(
        org_id=org_id, slug=SLUG, question="delete the western region"
    )

    assert allowed_run.verdict == SqlVerdict.ALLOWED
    assert rejected_run.verdict == SqlVerdict.REJECTED_WRITE
    assert rejected_run.denied_tables == ["analytics.region"]
    assert allowed_run.id != rejected_run.id

    async with db.session(org_id=org_id) as session:
        count = await session.scalar(
            select(func.count()).select_from(SqlRun).where(SqlRun.org_id == org_id)
        )
    assert count == 2


@pytest.mark.asyncio
async def test_a_rejected_write_is_a_durable_audit_row_but_an_allowed_read_is_not(
    datasource_service: DatasourceService, db: Database, org_id: OrgId, registered: None
) -> None:
    """`C3` deliverable 5 — the AST guard rejecting a write is the exact
    "watch a user be refused, and see why" moment the audit log exists for.
    An allowed read is not audited here: it is not a security decision."""
    from mnemos.features.identity.domain import UserId
    from mnemos.features.observability.adapters.repository import SqlAuditRepository

    user_id = UserId(uuid7())
    audit_repository = SqlAuditRepository(db, Uuid7Generator())

    def audited_service(model: FakeChatModel) -> SqlGenerationService:
        return SqlGenerationService(
            datasources=datasource_service,
            model=model,
            sql_runs=SqlRunRepository(db, Uuid7Generator()),
            audit=audit_repository,
        )

    allowed_model = FakeChatModel("```sql\nSELECT customer_id FROM analytics.customer\n```")
    await audited_service(allowed_model).generate(
        org_id=org_id, slug=SLUG, question="which customers exist?", user_id=user_id
    )

    rejected_model = FakeChatModel("```sql\nDELETE FROM analytics.region\n```")
    await audited_service(rejected_model).generate(
        org_id=org_id, slug=SLUG, question="delete the western region", user_id=user_id
    )

    events = await audit_repository.list_events(org_id=org_id, limit=10)
    [event] = events
    assert event.action == "datasource.query"
    assert event.outcome == "deny"
    assert event.actor_id == user_id
    assert event.reason is not None
    assert "not a read statement" in event.reason


@pytest.mark.asyncio
async def test_a_query_against_another_orgs_datasource_is_a_404(
    datasource_service: DatasourceService,
    db: Database,
    org_id: OrgId,
    other_org_id: OrgId,
    registered: None,
) -> None:
    """`require_datasource`'s lookup is `org_id`-scoped, so a datasource
    registered to `org_id` must be indistinguishable from a nonexistent one
    when queried as `other_org_id` — the same property RLS enforces at the
    database layer (CodingStandards §9 mandatory case 2), now proven for this
    new code path too rather than assumed inherited."""
    model = FakeChatModel("```sql\nSELECT 1\n```")
    service = _service(datasource_service, db, model)

    with pytest.raises(LookupError):
        await service.generate(org_id=other_org_id, slug=SLUG, question="anything")


@pytest.mark.asyncio
async def test_generate_raises_for_an_unregistered_slug(
    datasource_service: DatasourceService, db: Database, org_id: OrgId
) -> None:
    model = FakeChatModel("```sql\nSELECT 1\n```")
    service = _service(datasource_service, db, model)

    with pytest.raises(LookupError):
        await service.generate(org_id=org_id, slug="no-such-datasource", question="anything")


# --------------------------------------------------------------------------
# The second, independent defence — proven without going through the guard
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed(
    postgres: Postgres,
) -> None:
    """The AST guard is one defence; this is the other. Connects directly as
    `mnemos_ro` — bypassing `SqlGenerationService`, `guard_sql`, and every
    line of this deliverable entirely — and proves the write is refused by
    Postgres itself. Formalizes what deliverable 1 verified ad hoc while
    building the `postgres` fixture (TRACKER §5's `A3` note); this is the
    test that makes the two-defence claim a checked fact rather than
    something the guard alone is trusted to uphold.
    """
    conn = await asyncpg.connect(postgres.analytics_ro_dsn)
    try:
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute(
                "INSERT INTO analytics.region (region_name, country) VALUES ($1, $2)",
                "nowhere",
                "nowhere",
            )
    finally:
        await conn.close()
