"""What `DatasourceService` needs from persistence and the warehouse itself, as
`Protocol`s — the adapters satisfy these structurally, matching
`features/knowledge`'s pattern."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mnemos.core.types import SqlVerdict
from mnemos.features.datasources.domain import (
    DatasourceId,
    GlossaryTermRow,
    IntrospectedColumn,
    IntrospectedTable,
    SchemaObjectDraft,
    SqlRunId,
)
from mnemos.features.identity.domain import OrgId


@dataclass(frozen=True, slots=True)
class DatasourceRecord:
    id: DatasourceId
    org_id: OrgId
    slug: str
    name: str
    dialect: str
    dsn_encrypted: bytes
    read_only_role: str
    allowed_schemas: list[str]
    allowed_tables: list[str]
    introspected_at: datetime | None


class SchemaIntrospector(Protocol):
    async def introspect(
        self, *, dsn: str, schemas: list[str]
    ) -> tuple[list[IntrospectedTable], list[IntrospectedColumn]]: ...


class DatasourceRepository(Protocol):
    async def get_by_slug(self, *, org_id: OrgId, slug: str) -> DatasourceRecord | None: ...

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
    ) -> DatasourceRecord: ...

    async def mark_introspected(self, *, org_id: OrgId, datasource_id: DatasourceId) -> None: ...


class SchemaObjectRepository(Protocol):
    async def replace_all(
        self,
        *,
        org_id: OrgId,
        datasource_id: DatasourceId,
        drafts: list[SchemaObjectDraft],
    ) -> int:
        """Replace the cached schema for one datasource and return the row count.

        A full replace, not a diff: a dropped table must disappear from the
        cache on the next refresh, and refresh is already the explicit,
        infrequent action that makes a delete-then-insert cheap enough.
        """
        ...

    async def list_all(
        self, *, org_id: OrgId, datasource_id: DatasourceId
    ) -> list[SchemaObjectDraft]:
        """The cached schema, table rows before their columns — what
        `render_schema_context` renders. `SchemaObjectDraft` doubles as the
        read shape too; a cached row and a row about to be cached carry
        exactly the same fields."""
        ...


class GlossaryRepository(Protocol):
    async def ensure_terms(
        self, *, org_id: OrgId, datasource_id: DatasourceId, terms: list[GlossaryTermRow]
    ) -> int:
        """Idempotent per term, matched by `term` text: a term already present
        is left untouched, so re-running the seed never overwrites an edit
        made since. Returns how many were newly written."""
        ...

    async def list_terms(
        self, *, org_id: OrgId, datasource_id: DatasourceId
    ) -> list[GlossaryTermRow]: ...


@dataclass(frozen=True, slots=True)
class SqlRunRecord:
    id: SqlRunId
    org_id: OrgId
    datasource_id: DatasourceId
    attempt: int
    question: str
    generated_sql: str
    verdict: SqlVerdict
    verdict_detail: str | None
    authorized_tables: list[str]
    denied_tables: list[str]


class SqlRunRepository(Protocol):
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
        """Persist one generation attempt and its verdict, successful or not.

        `message_id` is nullable because deliverable 3 has no chat message to
        attach to yet (`flows/nl2sql/`, deliverable 4, is what will pass a
        real one) — every attempt is still recorded, just not yet linked to a
        conversation turn. `attempt` is supplied by the caller rather than
        computed here, so a future repair loop (deliverable 4,
        `Settings.sql_repair_attempts`) can record attempt 2, 3, ... against
        the same question without this port changing shape.
        """
        ...
