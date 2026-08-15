"""`ContentSourceRepository` over Postgres.

Every statement runs inside `Database.session(org_id=...)`, so RLS backs the
explicit `org_id` predicate (CodingStandards §6), the same discipline every
other repository in this codebase follows.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from mnemos.core.ids import IdGenerator
from mnemos.features.connectors.adapters.models import ContentSource
from mnemos.features.connectors.application.ports import ContentSourceRecord
from mnemos.features.connectors.domain import SourceId
from mnemos.features.identity.domain import OrgId
from mnemos.platform.db import Database


def _to_record(row: ContentSource) -> ContentSourceRecord:
    return ContentSourceRecord(
        id=SourceId(row.id),
        org_id=OrgId(row.org_id),
        slug=row.slug,
        name=row.name,
        kind=row.kind,
        config_encrypted=row.config_encrypted,
        is_enabled=row.is_enabled,
        created_at=row.created_at,
    )


class ContentSourceRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def get_by_slug(self, *, org_id: OrgId, slug: str) -> ContentSourceRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(ContentSource).where(
                    ContentSource.org_id == org_id, ContentSource.slug == slug
                )
            )
        return _to_record(row) if row is not None else None

    async def create(
        self,
        *,
        org_id: OrgId,
        slug: str,
        name: str,
        kind: str,
        config_encrypted: bytes,
    ) -> ContentSourceRecord:
        async with self._db.session(org_id=org_id) as session:
            row = ContentSource(
                id=self._ids.new(),
                org_id=org_id,
                slug=slug,
                name=name,
                kind=kind,
                config_encrypted=config_encrypted,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_record(row)

    async def list_all(self, *, org_id: OrgId) -> Sequence[ContentSourceRecord]:
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(ContentSource)
                    .where(ContentSource.org_id == org_id)
                    .order_by(ContentSource.slug)
                )
            ).all()
        return [_to_record(row) for row in rows]
