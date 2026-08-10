"""What `DatasourceService` needs from persistence and the warehouse itself, as
`Protocol`s — the adapters satisfy these structurally, matching
`features/knowledge`'s pattern."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mnemos.features.datasources.domain import (
    DatasourceId,
    IntrospectedColumn,
    IntrospectedTable,
    SchemaObjectDraft,
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
