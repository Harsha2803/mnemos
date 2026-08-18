"""The vector and lexical operators, over pgvector HNSW and pg_trgm.

**Authorization and currency are pushed into the scan, never applied after
ranking** (C4). `chunk_embedding.acl_tag_ids`/`trust_tier`/`is_current` are
denormalised from `document` for exactly this — the predicate is a column
comparison the planner can push through the HNSW/GIN index scan, not a join
back to `document` and not a Python-side filter after the database has
already decided the top-k. `test_acl_pushdown_beats_post_filtering_on_yield`
is the regression test that would catch "optimising" this into a post-filter.

**Superseded documents are excluded, not down-ranked** (C6):
`chunk_embedding.is_current` is flipped to `false` for every embedding under a
document the moment it is superseded (`KnowledgeRepository.mark_superseded`),
so `WHERE is_current` in both operators below is the whole of that guarantee.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import ColumnElement, Float, Row, cast, func, or_, select
from sqlalchemy.dialects import postgresql

from mnemos.features.identity.domain import OrgId
from mnemos.features.knowledge.adapters.models import Chunk, ChunkEmbedding, Document
from mnemos.features.knowledge.domain import ChunkId, DocumentId, RetrievedChunk
from mnemos.platform.db import Database


class SqlRetriever:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def vector_search(
        self,
        *,
        org_id: OrgId,
        caller_tag_ids: Sequence[UUID],
        query_vector: np.ndarray,
        k: int,
    ) -> list[RetrievedChunk]:
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector)
        query = (
            select(
                Chunk.id,
                Chunk.document_id,
                Document.title,
                Chunk.text,
                Chunk.token_count,
                Chunk.start_char,
                Chunk.end_char,
                Chunk.page_number,
                (1 - distance).label("score"),
            )
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            # Title only — a display field, never part of the authorization or
            # currency predicate, both of which stay on `chunk_embedding`'s
            # denormalised columns above.
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.org_id == org_id,
                ChunkEmbedding.is_current.is_(True),
                _acl_clause(caller_tag_ids),
            )
            .order_by(distance.asc())
            .limit(k)
        )
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.execute(query)).all()
        return [_row_to_chunk(r, operator_id="vector_search") for r in rows]

    async def lexical_search(
        self,
        *,
        org_id: OrgId,
        caller_tag_ids: Sequence[UUID],
        query_text: str,
        k: int,
    ) -> list[RetrievedChunk]:
        similarity = func.similarity(Chunk.text, query_text)
        query = (
            select(
                Chunk.id,
                Chunk.document_id,
                Document.title,
                Chunk.text,
                Chunk.token_count,
                Chunk.start_char,
                Chunk.end_char,
                Chunk.page_number,
                cast(similarity, Float).label("score"),
            )
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.org_id == org_id,
                ChunkEmbedding.is_current.is_(True),
                _acl_clause(caller_tag_ids),
                # `%` is pg_trgm's index-accelerated similarity operator —
                # this is what makes the GIN trigram index on `chunk.text`
                # (M2) actually fire, rather than a sequential scan the
                # `similarity()` call in the SELECT list alone would not avoid.
                Chunk.text.op("%")(query_text),
            )
            .order_by(similarity.desc())
            .limit(k)
        )
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.execute(query)).all()
        return [_row_to_chunk(r, operator_id="lexical_search") for r in rows]


def _acl_clause(caller_tag_ids: Sequence[UUID]) -> ColumnElement[bool]:
    """`acl_tag_ids = '{}'` means "public within the org"; otherwise the
    caller must hold at least one matching tag — `overlap` (`&&`), the same
    set-overlap argument `identity/domain/tags.py`'s `TagSet.overlaps` makes,
    pushed into SQL rather than checked in Python after the fact.

    A caller with **no** tags reaches only the public rows, and that branch is
    written without an `&&` at all: `ARRAY[]` with no elements has no
    inferable element type, and Postgres refuses it with
    `cannot determine type of empty array` rather than treating it as an empty
    uuid[]. Casting would work too; short-circuiting is clearer and saves the
    operator entirely for the commonest case.
    """
    public_only = ChunkEmbedding.acl_tag_ids == []
    if not caller_tag_ids:
        return public_only
    return or_(
        public_only,
        ChunkEmbedding.acl_tag_ids.overlap(
            postgresql.array(caller_tag_ids).cast(postgresql.ARRAY(postgresql.UUID(as_uuid=True)))
        ),
    )


def _row_to_chunk(row: Row[Any], *, operator_id: str) -> RetrievedChunk:
    """Both operators select the same nine columns in the same order, so one
    mapper serves both — by name rather than by position, which is what keeps
    adding a column to one query from silently shifting the other's fields."""
    return RetrievedChunk(
        chunk_id=ChunkId(row.id),
        document_id=DocumentId(row.document_id),
        document_title=row.title,
        text=row.text,
        score=float(row.score),
        operator_id=operator_id,
        token_count=row.token_count,
        char_start=row.start_char,
        char_end=row.end_char,
        page_number=row.page_number,
    )
