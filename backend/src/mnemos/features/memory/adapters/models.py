"""Governed memory: bitemporal claims and their supersession graph.

This is the schema the whole differentiator rests on, so the reasoning is worth
stating in full.

**Two time axes.** `valid_range` is *world time*: when the fact was true. `recorded_at`
/ `retracted_at` is *belief time*: when the system held it. They are independent —
learning today that something was true last March moves one and not the other. A
single `updated_at` column cannot answer "what did we believe on 1 June about
March", and that question is exactly what makes an answer auditable.

**Memory is never overwritten.** A new value closes the previous claim's
`valid_range` and writes a `supersedes` edge. Nothing is destroyed, so a stale
answer can always be traced to the belief that produced it.

**The exclusion constraint is the enforcement.** `EXCLUDE USING gist` over
`(org_id, subject_id, predicate, scope_hash, valid_range)` makes overlapping live
claims for the same fact impossible at the database level. Application code that
forgets to close the old row gets an integrity error rather than two live
truths. It is partial — `WHERE kind = 'fact' AND retracted_at IS NULL` — because
observations legitimately accumulate.

The constraint itself is DDL that SQLAlchemy's autogenerate does not reflect; it
is created explicitly in the migration and documented here so the two are read
together.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSTZRANGE, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.core.types import EdgeKind, MemoryKind, MemoryStatus, check_in
from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class Subject(Base, TimestampMixin):
    """What a claim is *about* — a user, a project, an entity in a document.

    Claims point at a subject row rather than a free-text name so that renaming
    an entity does not orphan its history.
    """

    __tablename__ = "subject"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "kind", "external_ref", name="uq_subject_org_id_kind_external_ref"
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Memory(Base):
    """One claim. Immutable once written except for the two closing timestamps."""

    __tablename__ = "memory"
    __table_args__ = (
        CheckConstraint(check_in("kind", MemoryKind), name="kind_valid"),
        CheckConstraint(check_in("status", MemoryStatus), name="status_valid"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="confidence_unit_interval"),
        # The hot path: live claims for one subject, newest belief first.
        Index(
            "ix_memory_org_id_subject_id_predicate",
            "org_id",
            "subject_id",
            "predicate",
            postgresql_where=text("retracted_at IS NULL"),
        ),
        Index("ix_memory_org_id_status_recorded_at", "org_id", "status", "recorded_at"),
        Index("ix_memory_valid_range", "valid_range", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subject.id", ondelete="CASCADE"), nullable=False
    )

    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    object_text: Mapped[str] = mapped_column(Text, nullable=False)
    object_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))

    # Scope is the qualifier that makes two claims about the same predicate
    # legitimately coexist (a preference "for project X" vs "for project Y").
    # Hashed because it participates in the exclusion constraint, and a hash is
    # a fixed-width equality key regardless of how baroque the scope gets.
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- world time ---
    valid_range: Mapped[object] = mapped_column(TSTZRANGE, nullable=False)

    # --- belief time ---
    recorded_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    retracted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1.0"))
    trust_tier: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("20"))

    # Provenance. A claim with no traceable origin is a rumour.
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Denormalized authorization, mirrored from the source document's tags. The
    # retrieval scan tests overlap against the caller's tags inside the WHERE
    # clause; a join here would defeat the index and force post-filtering.
    acl_tag_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )


class MemoryEdge(Base):
    """Typed relationships between claims — including how supersession happened.

    Conflict losers are demoted and recorded here, never silently dropped: a
    `contradicts` edge is the audit trail for why one claim outranked another.
    """

    __tablename__ = "memory_edge"
    __table_args__ = (
        UniqueConstraint("src_id", "dst_id", "kind", name="uq_memory_edge_src_id_dst_id_kind"),
        CheckConstraint(check_in("kind", EdgeKind), name="kind_valid"),
        CheckConstraint("src_id <> dst_id", name="no_self_edge"),
        Index("ix_memory_edge_dst_id_kind", "dst_id", "kind"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    src_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dst_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class MemoryEmbedding(Base):
    """Vectors for the memory retrieval operator.

    `halfvec` halves the index footprint at negligible recall cost for 384-dim
    embeddings, and HNSW is built over it directly.

    `org_id`, `acl_tag_ids` and `is_live` are denormalized onto this table on
    purpose. Authorization and currency must be evaluated *inside* the index
    scan; fetching top-k and then filtering returns fewer than k authorized rows
    and silently degrades recall for exactly the users with the fewest tags.
    """

    __tablename__ = "memory_embedding"
    __table_args__ = (
        UniqueConstraint("memory_id", "model", name="uq_memory_embedding_memory_id_model"),
        Index(
            "ix_memory_embedding_vector_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_with={"m": "16", "ef_construction": "64"},
        ),
        Index(
            "ix_memory_embedding_org_id_is_live",
            "org_id",
            "is_live",
            postgresql_where=text("is_live"),
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[object] = mapped_column(HALFVEC(384), nullable=False)

    is_live: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    acl_tag_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
