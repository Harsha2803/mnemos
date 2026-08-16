"""`KnowledgeRepository` over Postgres: documents, chunks, and their embeddings.

Every statement runs inside `Database.session(org_id=...)`, so RLS backs the
explicit `org_id` predicate (CodingStandards §6), the same discipline every
other repository in this codebase follows.

**Re-uploading identical bytes is a no-op**, enforced by
`uq_document_org_id_content_sha256` and checked here *before* chunking or
embedding runs, so a duplicate upload costs one `SELECT` rather than the CPU
work of processing content that is already there.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import UUID

import numpy as np
from sqlalchemy import func, select, update

from mnemos.core.ids import IdGenerator
from mnemos.features.identity.adapters.models import Tag
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.adapters.models import Chunk, ChunkEmbedding, Document
from mnemos.features.knowledge.domain import DocumentId, DocumentSummary, RawChunk
from mnemos.platform.db import Database


class KnowledgeRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def resolve_tag_ids(self, *, org_id: OrgId, slugs: Sequence[str]) -> list[UUID]:
        """The caller's tag *ids* — what `document.acl_tag_ids`/
        `chunk_embedding.acl_tag_ids` actually store — from the slugs
        `Principal.tags` carries. `AuthenticatedCaller` only ever hydrates
        slugs (M3.1), so this is the one extra read the retrieval path needs
        that the guard's own hydration does not already do."""
        if not slugs:
            return []
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(Tag.id).where(Tag.org_id == org_id, Tag.slug.in_(slugs))
                )
            ).all()
        return list(rows)

    async def find_by_content_hash(
        self, *, org_id: OrgId, content_sha256: str
    ) -> DocumentSummary | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(Document).where(
                    Document.org_id == org_id, Document.content_sha256 == content_sha256
                )
            )
        return await self._summary(org_id, row) if row is not None else None

    async def create_document(
        self,
        *,
        org_id: OrgId,
        user_id: UserId | None,
        title: str,
        media_type: str,
        byte_size: int,
        content_sha256: str,
        source_kind: str,
        source_uri: str,
        object_key: str,
    ) -> DocumentSummary:
        new_id = self._ids.new()
        async with self._db.session(org_id=org_id) as session:
            row = Document(
                id=new_id,
                org_id=org_id,
                title=title,
                media_type=media_type,
                byte_size=byte_size,
                content_sha256=content_sha256,
                source_kind=source_kind,
                source_uri=source_uri,
                object_key=object_key,
                status="pending",
                lineage_key=str(new_id),
                uploaded_by=user_id,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
        return DocumentSummary(
            id=DocumentId(row.id),
            org_id=OrgId(row.org_id),
            title=row.title,
            media_type=row.media_type,
            byte_size=row.byte_size,
            status=row.status,
            superseded_by=None,
            chunk_count=0,
            created_at=row.created_at,
        )

    async def add_chunks(
        self,
        *,
        org_id: OrgId,
        document_id: DocumentId,
        raw_chunks: Sequence[RawChunk],
        vectors: np.ndarray,
        model_name: str,
        acl_tag_ids: Sequence[object],
        trust_tier: int,
    ) -> None:
        """One `chunk` row and one `chunk_embedding` row per `RawChunk`, in the
        document's own transaction — a chunk with no embedding is not
        retrievable and should not exist even transiently."""
        async with self._db.session(org_id=org_id) as session:
            for i, raw in enumerate(raw_chunks):
                chunk_id = self._ids.new()
                session.add(
                    Chunk(
                        id=chunk_id,
                        org_id=org_id,
                        document_id=document_id,
                        ordinal=raw.ordinal,
                        text=raw.content,
                        token_count=raw.token_count,
                        start_char=raw.char_start,
                        end_char=raw.char_end,
                        page_number=raw.page,
                        heading_path=[raw.heading] if raw.heading else [],
                        content_sha256=_sha256(raw.content),
                    )
                )
                session.add(
                    ChunkEmbedding(
                        id=self._ids.new(),
                        org_id=org_id,
                        chunk_id=chunk_id,
                        document_id=document_id,
                        model=model_name,
                        dim=int(vectors.shape[1]),
                        embedding=vectors[i],
                        is_current=True,
                        acl_tag_ids=list(acl_tag_ids),
                        trust_tier=trust_tier,
                    )
                )
            await session.execute(
                update(Document).where(Document.id == document_id).values(status="ready")
            )

    async def list_documents(self, *, org_id: OrgId) -> Sequence[DocumentSummary]:
        chunk_counts = (
            select(Chunk.document_id, func.count().label("n"))
            .group_by(Chunk.document_id)
            .subquery()
        )
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.execute(
                    select(Document, func.coalesce(chunk_counts.c.n, 0))
                    .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
                    .where(Document.org_id == org_id, Document.deleted_at.is_(None))
                    .order_by(Document.created_at.desc())
                )
            ).all()
        return [_summary_row(row, count) for row, count in rows]

    async def get_document(
        self, *, org_id: OrgId, document_id: DocumentId
    ) -> DocumentSummary | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(Document).where(Document.org_id == org_id, Document.id == document_id)
            )
        return await self._summary(org_id, row) if row is not None else None

    async def delete_document(self, *, org_id: OrgId, document_id: DocumentId) -> str | None:
        """Hard delete — `chunk`/`chunk_embedding` cascade via their FKs.
        Returns the `object_key` so the caller can remove the bytes too."""
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(Document).where(Document.org_id == org_id, Document.id == document_id)
            )
            if row is None:
                return None
            object_key = row.object_key
            await session.delete(row)
        return object_key

    async def mark_superseded(
        self, *, org_id: OrgId, old_document_id: DocumentId, new_document_id: DocumentId
    ) -> None:
        """C6: excluded from the scan, not down-ranked. `chunk_embedding.is_current`
        is what the retrieval scan actually tests (denormalised so the scan
        never joins back to `document`), so both it and `document.superseded_by`
        are updated in the same transaction."""
        async with self._db.session(org_id=org_id) as session:
            await session.execute(
                update(Document)
                .where(Document.org_id == org_id, Document.id == old_document_id)
                .values(superseded_by=new_document_id)
            )
            await session.execute(
                update(ChunkEmbedding)
                .where(
                    ChunkEmbedding.org_id == org_id,
                    ChunkEmbedding.document_id == old_document_id,
                )
                .values(is_current=False)
            )

    async def _summary(self, org_id: OrgId, row: Document) -> DocumentSummary:
        async with self._db.session(org_id=org_id) as session:
            count = await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == row.id)
            )
        return DocumentSummary(
            id=DocumentId(row.id),
            org_id=OrgId(row.org_id),
            title=row.title,
            media_type=row.media_type,
            byte_size=row.byte_size,
            status=row.status,
            superseded_by=DocumentId(row.superseded_by) if row.superseded_by else None,
            chunk_count=count or 0,
            created_at=row.created_at,
        )


def _summary_row(row: Document, count: int) -> DocumentSummary:
    return DocumentSummary(
        id=DocumentId(row.id),
        org_id=OrgId(row.org_id),
        title=row.title,
        media_type=row.media_type,
        byte_size=row.byte_size,
        status=row.status,
        superseded_by=DocumentId(row.superseded_by) if row.superseded_by else None,
        chunk_count=count,
        created_at=row.created_at,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
