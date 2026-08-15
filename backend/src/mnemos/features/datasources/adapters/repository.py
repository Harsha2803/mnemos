"""`DatasourceRepository` and `SchemaObjectRepository` over Postgres.

Every statement runs inside `Database.session(org_id=...)`, so RLS backs the
explicit `org_id` predicate (CodingStandards §6) — the same discipline
`features/knowledge`'s repository follows.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select

from mnemos.core.ids import IdGenerator
from mnemos.core.types import SqlVerdict
from mnemos.features.datasources.adapters.models import (
    GlossaryTerm,
    SqlDatasource,
    SqlRun,
    SqlSchemaObject,
)
from mnemos.features.datasources.application.ports import DatasourceRecord, SqlRunRecord
from mnemos.features.datasources.domain import (
    DatasourceId,
    GlossaryTermRow,
    SchemaObjectDraft,
    SqlRunId,
)
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

    async def list_all(
        self, *, org_id: OrgId, datasource_id: DatasourceId
    ) -> list[SchemaObjectDraft]:
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(SqlSchemaObject)
                    .where(
                        SqlSchemaObject.org_id == org_id,
                        SqlSchemaObject.datasource_id == datasource_id,
                    )
                    # Table row (`column_name is null`) before its columns —
                    # `render_schema_context` relies on seeing a table's own
                    # row before it starts collecting that table's columns.
                    .order_by(SqlSchemaObject.table_name, SqlSchemaObject.column_name.nulls_first())
                )
            ).all()
        return [
            SchemaObjectDraft(
                schema_name=r.schema_name,
                table_name=r.table_name,
                column_name=r.column_name,
                data_type=r.data_type,
                is_nullable=r.is_nullable,
                row_estimate=r.row_estimate,
            )
            for r in rows
        ]


class GlossaryRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def ensure_terms(
        self, *, org_id: OrgId, datasource_id: DatasourceId, terms: list[GlossaryTermRow]
    ) -> int:
        async with self._db.session(org_id=org_id) as session:
            existing = set(
                (
                    await session.scalars(
                        select(GlossaryTerm.term).where(
                            GlossaryTerm.org_id == org_id,
                            GlossaryTerm.datasource_id == datasource_id,
                        )
                    )
                ).all()
            )
            to_add = [t for t in terms if t.term not in existing]
            session.add_all(
                [
                    GlossaryTerm(
                        id=self._ids.new(),
                        org_id=org_id,
                        datasource_id=datasource_id,
                        term=t.term,
                        definition=t.definition,
                        sql_expression=t.sql_expression,
                        synonyms=t.synonyms,
                    )
                    for t in to_add
                ]
            )
        return len(to_add)

    async def list_terms(
        self, *, org_id: OrgId, datasource_id: DatasourceId
    ) -> list[GlossaryTermRow]:
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(GlossaryTerm)
                    .where(
                        GlossaryTerm.org_id == org_id,
                        GlossaryTerm.datasource_id == datasource_id,
                    )
                    .order_by(GlossaryTerm.term)
                )
            ).all()
        return [
            GlossaryTermRow(
                term=r.term,
                definition=r.definition,
                sql_expression=r.sql_expression,
                synonyms=list(r.synonyms),
            )
            for r in rows
        ]


def _to_sql_run_record(row: SqlRun) -> SqlRunRecord:
    return SqlRunRecord(
        id=SqlRunId(row.id),
        org_id=OrgId(row.org_id),
        datasource_id=DatasourceId(row.datasource_id),
        attempt=row.attempt,
        question=row.question,
        generated_sql=row.generated_sql,
        verdict=SqlVerdict(row.verdict),
        verdict_detail=row.verdict_detail,
        authorized_tables=list(row.authorized_tables),
        denied_tables=list(row.denied_tables),
        message_id=row.message_id,
        executed=row.executed,
        row_count=row.row_count,
        truncated=row.truncated,
        duration_ms=row.duration_ms,
        error_code=row.error_code,
        error_detail=row.error_detail,
    )


class SqlRunRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def record_attempt(
        self,
        *,
        org_id: OrgId,
        datasource_id: DatasourceId,
        message_id: uuid.UUID | None,
        attempt: int,
        question: str,
        generated_sql: str,
        verdict: SqlVerdict,
        verdict_detail: str | None,
        authorized_tables: list[str],
        denied_tables: list[str],
    ) -> SqlRunRecord:
        async with self._db.session(org_id=org_id) as session:
            row = SqlRun(
                id=self._ids.new(),
                org_id=org_id,
                datasource_id=datasource_id,
                message_id=message_id,
                attempt=attempt,
                question=question,
                generated_sql=generated_sql,
                verdict=verdict.value,
                verdict_detail=verdict_detail,
                authorized_tables=authorized_tables,
                denied_tables=denied_tables,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_sql_run_record(row)

    async def record_execution(
        self,
        *,
        org_id: OrgId,
        sql_run_id: SqlRunId,
        executed: bool,
        row_count: int | None,
        truncated: bool,
        duration_ms: int | None,
        error_code: str | None,
        error_detail: str | None,
    ) -> SqlRunRecord:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(SqlRun).where(SqlRun.org_id == org_id, SqlRun.id == sql_run_id)
            )
            if row is None:
                raise LookupError(f"no sql_run {sql_run_id} for org {org_id}")
            row.executed = executed
            row.row_count = row_count
            row.truncated = truncated
            row.duration_ms = duration_ms
            row.error_code = error_code
            row.error_detail = error_detail
            await session.flush()
            await session.refresh(row)
            return _to_sql_run_record(row)

    async def attach_to_message(
        self, *, org_id: OrgId, sql_run_id: SqlRunId, message_id: uuid.UUID
    ) -> None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(SqlRun).where(SqlRun.org_id == org_id, SqlRun.id == sql_run_id)
            )
            if row is None:
                raise LookupError(f"no sql_run {sql_run_id} for org {org_id}")
            row.message_id = message_id
