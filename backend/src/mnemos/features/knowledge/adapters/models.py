"""Knowledge: documents, chunks, embeddings, and the ingestion job ledger.

**Document currency is a column, not a ranking signal.** When revision 3 of a
policy lands, revisions 1 and 2 get `superseded_by` set and drop out of the scan
entirely. Down-ranking is not enough: obsolete text is often *more* lexically
similar to a question than the current text, because the question was written
against the vocabulary people remember.

**Chunks keep character offsets.** `start_char`/`end_char` are what let a
citation resolve to a highlight in the original PDF instead of a page number and
an apology.

**Jobs heartbeat.** A worker that dies mid-ingest leaves a row in `running`
forever unless something notices. `heartbeat_at` plus `attempts` makes stuck
detection a query, and `ingest_job_event` keeps the status history so a failure
can be explained after the fact rather than guessed at.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.core.types import ConnectorKind, DocumentStatus, JobStatus, check_in
from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class Collection(Base, TimestampMixin):
    """A named grouping of documents. Retrieval can be scoped to one."""

    __tablename__ = "collection"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_collection_org_id_slug"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Document(Base, TimestampMixin):
    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint(check_in("status", DocumentStatus), name="status_valid"),
        CheckConstraint(check_in("source_kind", ConnectorKind), name="source_kind_valid"),
        # Content-addressed: re-uploading the same bytes is a no-op rather than a
        # duplicate that competes with itself in retrieval.
        UniqueConstraint("org_id", "content_sha256", name="uq_document_org_id_content_sha256"),
        Index(
            "ix_document_org_id_collection_id_status",
            "org_id",
            "collection_id",
            "status",
        ),
        Index("ix_document_org_id_lineage_key", "org_id", "lineage_key"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=sa_text("'pending'")
    )

    # --- currency ------------------------------------------------------------
    # `lineage_key` groups revisions of the same logical document. `revision`
    # orders them. `superseded_by` is what the retrieval scan tests, so the check
    # is an index probe rather than a subquery over the lineage.
    lineage_key: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("1"))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL"), nullable=True
    )
    valid_from: Mapped[datetime] = mapped_column(server_default=sa_text("now()"), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(nullable=True)

    acl_tag_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=sa_text("'{}'::uuid[]")
    )
    trust_tier: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sa_text("10")
    )
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")
    )

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Chunk(Base):
    __tablename__ = "chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_chunk_document_id_ordinal"),
        Index("ix_chunk_org_id_document_id", "org_id", "document_id"),
        # Lexical operator. GIN over trigrams, so the BM25-ish arm does not
        # degrade into a sequential scan as the corpus grows.
        Index(
            "ix_chunk_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Offsets into the *original* extracted text, so a citation highlights the
    # source rather than a re-rendered copy of it.
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )

    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=sa_text("now()"), nullable=False)


class ChunkEmbedding(Base):
    """Same denormalization argument as `memory_embedding`: authorization and
    currency are index-scan predicates, not post-filters."""

    __tablename__ = "chunk_embedding"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model", name="uq_chunk_embedding_chunk_id_model"),
        Index(
            "ix_chunk_embedding_vector_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_with={"m": "16", "ef_construction": "64"},
        ),
        Index(
            "ix_chunk_embedding_org_id_is_current",
            "org_id",
            "is_current",
            postgresql_where=sa_text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunk.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[object] = mapped_column(HALFVEC(384), nullable=False)

    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa_text("true")
    )
    acl_tag_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=sa_text("'{}'::uuid[]")
    )
    trust_tier: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sa_text("10")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=sa_text("now()"), nullable=False)


class IngestJob(Base, TimestampMixin):
    __tablename__ = "ingest_job"
    __table_args__ = (
        CheckConstraint(check_in("status", JobStatus), name="status_valid"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # Claim query: oldest queued job first, and stuck-job sweep.
        Index("ix_ingest_job_status_heartbeat_at", "status", "heartbeat_at"),
        Index("ix_ingest_job_org_id_created_at", "org_id", "created_at"),
        UniqueConstraint("idempotency_key", name="uq_ingest_job_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=sa_text("'queued'")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")
    )

    # Single-owner claim: exactly one worker may hold a job, and it must keep
    # proving it is alive. A lease with no heartbeat is a lock that leaks.
    owner_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("3"))
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Progress, so a long ingest is observable rather than a spinner.
    total_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    done_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))


class IngestJobEvent(Base):
    """Append-only status history. Explains a failure instead of overwriting it."""

    __tablename__ = "ingest_job_event"
    __table_args__ = (Index("ix_ingest_job_event_job_id_occurred_at", "job_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_job.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(server_default=sa_text("now()"), nullable=False)
