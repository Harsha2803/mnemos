"""`SchemaIntrospector` over Postgres: `information_schema` for column shapes,
`pg_class` for row estimates.

Connects with the datasource's own DSN — the role that can describe the schema
is the role that can query it, so introspection never learns about a table
`mnemos_ro` could not itself read. A short-lived engine, disposed after one
call: introspection is explicit and rare (`DatasourceService.refresh_schema`),
not a connection the flow holds open the way `Database` holds the app's own.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mnemos.features.datasources.domain import IntrospectedColumn, IntrospectedTable

_COLUMNS_SQL = text(
    """
    SELECT table_schema, table_name, column_name, data_type,
           (is_nullable = 'YES') AS is_nullable
      FROM information_schema.columns
     WHERE table_schema = ANY(:schemas)
     ORDER BY table_schema, table_name, ordinal_position
    """
)

# `reltuples` is a planner estimate, not `count(*)` — exact enough for the
# generator to reason about table size and cheap enough to run on every
# refresh, where `count(*)` on a 900-row demo table is fine but on a real
# warehouse table is the query the read-only role should not be forced into.
_TABLES_SQL = text(
    """
    SELECT n.nspname AS table_schema, c.relname AS table_name,
           NULLIF(c.reltuples, -1)::bigint AS row_estimate
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = ANY(:schemas) AND c.relkind = 'r'
     ORDER BY n.nspname, c.relname
    """
)


class PostgresIntrospector:
    async def introspect(
        self, *, dsn: str, schemas: list[str]
    ) -> tuple[list[IntrospectedTable], list[IntrospectedColumn]]:
        engine = create_async_engine(dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                table_rows = (await conn.execute(_TABLES_SQL, {"schemas": schemas})).all()
                column_rows = (await conn.execute(_COLUMNS_SQL, {"schemas": schemas})).all()
        finally:
            await engine.dispose()

        tables = [
            IntrospectedTable(
                schema_name=row.table_schema,
                table_name=row.table_name,
                row_estimate=row.row_estimate,
            )
            for row in table_rows
        ]
        columns = [
            IntrospectedColumn(
                schema_name=row.table_schema,
                table_name=row.table_name,
                column_name=row.column_name,
                data_type=row.data_type,
                is_nullable=row.is_nullable,
            )
            for row in column_rows
        ]
        return tables, columns
