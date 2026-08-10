"""`DatasourceRepository` and `SchemaObjectRepository` over Postgres.

Every statement runs inside `Database.session(org_id=...)`, so RLS backs the
explicit `org_id` predicate (CodingStandards §6) — the same discipline
`features/knowledge`'s repository follows.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select

from mnemos.core.ids import IdGenerator
from mnemos.features.datasources.adapters.models import SqlDatasource, SqlSchemaObject
from mnemos.features.datasources.application.ports import DatasourceRecord
from mnemos.features.datasources.domain import DatasourceId, SchemaObjectDraft
from mnemos.features.identity.domain import OrgId
from mnemos.platform.db import Database


def _to_record(row: SqlDatasource) -> DatasourceRecord:
    return DatasourceRecord(
        id=DatasourceId(row.id),
        org_id=OrgId(row.org_id),
        slug=row.slug,
        name=row.name,
        dialect=row.dialect,
        dsn_encrypted=row.dsn_encrypted,
        read_only_role=row.read_only_role,
        allowed_schemas=list(row.allowed_schemas),
        allowed_tables=list(row.allowed_tables),
        introspected_at=row.introspected_at,
    )


class DatasourceRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def get_by_slug(self, *, org_id: OrgId, slug: str) -> DatasourceRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(SqlDatasource).where(
                    SqlDatasource.org_id == org_id, SqlDatasource.slug == slug
                )
            )
        return _to_record(row) if row is not None else None

    async def ensure_datasource(
        self,
        *,
        org_id: OrgId,
        slug: str,
        name: str,
        description: str,
        dsn_encrypted: bytes,
        read_only_role: str,
        allowed_schemas: list[str],
    ) -> DatasourceRecord:
        """Idempotent: a second call with the same slug returns the existing
        row unchanged, matching `mnemosctl bootstrap`'s own idempotence."""
        existing = await self.get_by_slug(org_id=org_id, slug=slug)
        if existing is not None:
            return existing

        async with self._db.session(org_id=org_id) as session:
            row = SqlDatasource(
                id=self._ids.new(),
                org_id=org_id,
                slug=slug,
                name=name,
                description=description,
                dsn_encrypted=dsn_encrypted,
                read_only_role=read_only_role,
                allowed_schemas=allowed_schemas,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_record(row)

    async def mark_introspected(self, *, org_id: OrgId, datasource_id: DatasourceId) -> None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(SqlDatasource).where(
                    SqlDatasource.org_id == org_id, SqlDatasource.id == datasource_id
                )
            )
            if row is not None:
                row.introspected_at = func.now()


class SchemaObjectRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def replace_all(
        self,
        *,
        org_id: OrgId,
        datasource_id: DatasourceId,
        drafts: list[SchemaObjectDraft],
    ) -> int:
        async with self._db.session(org_id=org_id) as session:
            await session.execute(
                delete(SqlSchemaObject).where(
                    SqlSchemaObject.org_id == org_id,
                    SqlSchemaObject.datasource_id == datasource_id,
                )
            )
            rows = [
                SqlSchemaObject(
                    id=self._ids.new(),
                    org_id=org_id,
                    datasource_id=datasource_id,
                    schema_name=d.schema_name,
                    table_name=d.table_name,
                    column_name=d.column_name,
                    data_type=d.data_type,
                    is_nullable=d.is_nullable,
                    row_estimate=d.row_estimate,
                )
                for d in drafts
            ]
            session.add_all(rows)
        return len(rows)
