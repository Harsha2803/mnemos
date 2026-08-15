"""`A3` deliverable 1 — schema introspection, against a real Postgres.

The claims here are claims about a real warehouse: that introspection only
ever sees the schemas the datasource is allowlisted for, that a refresh
replaces rather than accumulates duplicate rows, and that the registered DSN
round-trips through encryption. A fake introspector would only prove the fake
returns what it was told to — `test_knowledge_endpoints.py` makes the same
argument about retrieval.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

import mnemos.platform.models  # noqa: F401
from mnemos.core.crypto import DsnCipher
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.features.datasources.adapters.executor import PostgresExecutor
from mnemos.features.datasources.adapters.introspection import PostgresIntrospector
from mnemos.features.datasources.adapters.repository import (
    DatasourceRepository,
    GlossaryRepository,
    SchemaObjectRepository,
)
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.identity.domain import OrgId
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

# `Base.metadata` only knows about a table once its model class has been
# imported somewhere in the process — `sql_datasource.org_id`'s foreign key to
# `org.id` cannot resolve otherwise. `platform.models` (imported above,
# unused directly) is the module that imports every model; a running process
# always has it loaded before its first query, and a test process needs the
# same nudge.

DSN_KEY = "zqQeIteGh6YP2kybnsto8GE8W38N_u9yJhINMNKDpMg="
SLUG = "sales-warehouse"


@pytest_asyncio.fixture
async def org_id(postgres: Postgres) -> AsyncIterator[OrgId]:
    new_org = OrgId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            new_org,
            f"ds-org-{new_org.hex[:8]}",
            "Datasource Test Org",
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
def service(db: Database, postgres: Postgres) -> DatasourceService:
    ids = Uuid7Generator()
    return DatasourceService(
        datasources=DatasourceRepository(db, ids),
        schema_objects=SchemaObjectRepository(db, ids),
        introspector=PostgresIntrospector(),
        cipher=DsnCipher(DSN_KEY),
        glossary=GlossaryRepository(db, ids),
        executor=PostgresExecutor(),
    )


@pytest.mark.asyncio
async def test_introspector_reads_only_the_allowed_schema(postgres: Postgres) -> None:
    tables, columns = await PostgresIntrospector().introspect(
        dsn=postgres.analytics_ro_url, schemas=["analytics"]
    )

    table_names = {t.table_name for t in tables}
    assert table_names == {"region", "product", "customer", "sales_order"}
    sales_order_columns = {c.column_name for c in columns if c.table_name == "sales_order"}
    assert sales_order_columns == {
        "order_id",
        "customer_id",
        "product_id",
        "ordered_on",
        "quantity",
        "net_amount",
        "status",
    }


@pytest.mark.asyncio
async def test_introspector_sees_nothing_outside_the_requested_schema(postgres: Postgres) -> None:
    tables, columns = await PostgresIntrospector().introspect(
        dsn=postgres.analytics_ro_url, schemas=["a_schema_that_does_not_exist"]
    )
    assert tables == []
    assert columns == []


@pytest.mark.asyncio
async def test_refresh_schema_caches_rows_and_marks_introspected_at(
    service: DatasourceService, postgres: Postgres, org_id: OrgId
) -> None:
    datasource = await service.register(
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )
    assert datasource.introspected_at is None

    rows_written = await service.refresh_schema(org_id=org_id, slug=SLUG)
    assert rows_written > 0

    refreshed = await service.register(  # ensure_datasource is idempotent, so this is a re-read
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )
    assert refreshed.introspected_at is not None


@pytest.mark.asyncio
async def test_a_second_refresh_replaces_rather_than_accumulates(
    service: DatasourceService, postgres: Postgres, org_id: OrgId, db: Database
) -> None:
    await service.register(
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )

    first_count = await service.refresh_schema(org_id=org_id, slug=SLUG)
    second_count = await service.refresh_schema(org_id=org_id, slug=SLUG)
    assert first_count == second_count

    from sqlalchemy import func, select

    from mnemos.features.datasources.adapters.models import SqlSchemaObject

    async with db.session(org_id=org_id) as session:
        live_count = await session.scalar(
            select(func.count())
            .select_from(SqlSchemaObject)
            .where(SqlSchemaObject.org_id == org_id)
        )
    assert live_count == second_count


@pytest.mark.asyncio
async def test_register_is_idempotent(
    service: DatasourceService, postgres: Postgres, org_id: OrgId
) -> None:
    first = await service.register(
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )
    second = await service.register(
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )
    assert first.id == second.id


@pytest.mark.asyncio
async def test_register_rejects_an_empty_allowlist(
    service: DatasourceService, org_id: OrgId
) -> None:
    with pytest.raises(ValueError, match="allowed_schemas"):
        await service.register(
            org_id=org_id,
            slug=SLUG,
            name="Sales Warehouse",
            description="test",
            dsn="postgresql+asyncpg://irrelevant/irrelevant",
            read_only_role="mnemos_ro",
            allowed_schemas=[],
        )


@pytest.mark.asyncio
async def test_the_stored_dsn_is_encrypted_and_round_trips(
    service: DatasourceService, postgres: Postgres, org_id: OrgId
) -> None:
    datasource = await service.register(
        org_id=org_id,
        slug=SLUG,
        name="Sales Warehouse",
        description="test",
        dsn=postgres.analytics_ro_url,
        read_only_role="mnemos_ro",
        allowed_schemas=["analytics"],
    )

    assert postgres.analytics_ro_url.encode() not in datasource.dsn_encrypted
    assert DsnCipher(DSN_KEY).decrypt(datasource.dsn_encrypted) == postgres.analytics_ro_url


@pytest.mark.asyncio
async def test_refresh_schema_raises_for_an_unregistered_slug(
    service: DatasourceService, org_id: OrgId
) -> None:
    with pytest.raises(LookupError):
        await service.refresh_schema(org_id=org_id, slug="no-such-datasource")
