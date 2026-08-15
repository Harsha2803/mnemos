"""`A3` deliverable 2 — the business glossary, against a real Postgres.

The claims here are about a real round trip: seeding a term twice writes it
once, `render_context` reads back exactly what deliverable 1's cache and this
deliverable's glossary hold, and an unregistered datasource fails with a
plain `LookupError` rather than silently returning nothing. A fake repository
would only prove the fake returns what it was told to —
`test_datasources_introspection.py` makes the same argument about
introspection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

import mnemos.platform.models  # noqa: F401
from mnemos.core.crypto import DsnCipher
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.features.datasources.adapters.introspection import PostgresIntrospector
from mnemos.features.datasources.adapters.repository import (
    DatasourceRepository,
    GlossaryRepository,
    SchemaObjectRepository,
)
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.datasources.domain import GlossaryTermRow
from mnemos.features.identity.domain import OrgId
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

DSN_KEY = "zqQeIteGh6YP2kybnsto8GE8W38N_u9yJhINMNKDpMg="
SLUG = "sales-warehouse"

TERMS = [
    GlossaryTermRow(
        term="revenue",
        definition="Net amount collected for completed sales orders.",
        sql_expression="SUM(analytics.sales_order.net_amount) WHERE status = 'completed'",
        synonyms=["sales"],
    ),
    GlossaryTermRow(
        term="active customer",
        definition="A customer with an order in the last 90 days.",
        sql_expression=None,
        synonyms=[],
    ),
]


@pytest_asyncio.fixture
async def org_id(postgres: Postgres) -> AsyncIterator[OrgId]:
    new_org = OrgId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            new_org,
            f"ds-glossary-org-{new_org.hex[:8]}",
            "Datasource Glossary Test Org",
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
def service(db: Database) -> DatasourceService:
    ids = Uuid7Generator()
    return DatasourceService(
        datasources=DatasourceRepository(db, ids),
        schema_objects=SchemaObjectRepository(db, ids),
        introspector=PostgresIntrospector(),
        cipher=DsnCipher(DSN_KEY),
        glossary=GlossaryRepository(db, ids),
    )


@pytest_asyncio.fixture
async def registered(service: DatasourceService, postgres: Postgres, org_id: OrgId) -> None:
    await service.register(
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )


@pytest.mark.asyncio
async def test_seed_glossary_writes_every_term_on_the_first_call(
    service: DatasourceService, org_id: OrgId, registered: None
) -> None:
    written = await service.seed_glossary(org_id=org_id, slug=SLUG, terms=TERMS)
    assert written == len(TERMS)


@pytest.mark.asyncio
async def test_seed_glossary_is_idempotent(
    service: DatasourceService, org_id: OrgId, registered: None
) -> None:
    await service.seed_glossary(org_id=org_id, slug=SLUG, terms=TERMS)
    second = await service.seed_glossary(org_id=org_id, slug=SLUG, terms=TERMS)
    assert second == 0


@pytest.mark.asyncio
async def test_seed_glossary_never_overwrites_a_term_edited_since(
    service: DatasourceService, org_id: OrgId, registered: None
) -> None:
    """A term already present is matched by its `term` text and left alone —
    re-seeding must not clobber an edit an operator made in between runs."""
    await service.seed_glossary(
        org_id=org_id,
        slug=SLUG,
        terms=[
            GlossaryTermRow(
                term="revenue", definition="the original definition", sql_expression=None
            )
        ],
    )
    await service.seed_glossary(
        org_id=org_id,
        slug=SLUG,
        terms=[
            GlossaryTermRow(
                term="revenue", definition="a different seed definition", sql_expression=None
            )
        ],
    )

    context = await service.render_context(org_id=org_id, slug=SLUG)
    assert "the original definition" in context
    assert "a different seed definition" not in context


@pytest.mark.asyncio
async def test_seed_glossary_raises_for_an_unregistered_slug(
    service: DatasourceService, org_id: OrgId
) -> None:
    with pytest.raises(LookupError):
        await service.seed_glossary(org_id=org_id, slug="no-such-datasource", terms=TERMS)


@pytest.mark.asyncio
async def test_render_context_combines_the_cached_schema_and_the_glossary(
    service: DatasourceService, org_id: OrgId, registered: None
) -> None:
    await service.refresh_schema(org_id=org_id, slug=SLUG)
    await service.seed_glossary(org_id=org_id, slug=SLUG, terms=TERMS)

    context = await service.render_context(org_id=org_id, slug=SLUG)

    assert "## Schema" in context
    assert "analytics.sales_order" in context
    assert "## Business glossary" in context
    assert "**revenue**" in context
    assert context.index("## Schema") < context.index("## Business glossary")


@pytest.mark.asyncio
async def test_render_context_is_empty_before_introspection_or_seeding(
    service: DatasourceService, org_id: OrgId, registered: None
) -> None:
    assert await service.render_context(org_id=org_id, slug=SLUG) == ""


@pytest.mark.asyncio
async def test_render_context_raises_for_an_unregistered_slug(
    service: DatasourceService, org_id: OrgId
) -> None:
    with pytest.raises(LookupError):
        await service.render_context(org_id=org_id, slug="no-such-datasource")
