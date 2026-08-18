"""Context: the compiled prompt, persisted as an artifact.

The claim this project makes is that context is *compiled*, not concatenated. A
compiled artifact you cannot inspect is just a string with better marketing, so
the bundle and every item in it are stored.

`digest` is a canonical hash over the plan and the admitted items. Two compiles
with the same inputs produce the same digest, which is what makes the benchmark
reproducible and what makes `:replay` meaningful.

`bundle_item.acl_rule_id` records *which* authorization decision admitted an
item. When a tool call is later denied by trust tier, the denial can name the
offending source rather than saying "something in your context".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.core.types import OperatorKind, check_in
from mnemos.platform.db import Base, org_fk, pk_column


class ContextPlan(Base):
    """The budget allocation decided *before* any operator ran.

    Planning first is what stops the compiler from buying boilerplate: section
    floors and ceilings are set against calibrated utility, not against whatever
    retrieval happened to return.
    """

    __tablename__ = "context_plan"
    __table_args__ = (Index("ix_context_plan_org_id_created_at", "org_id", "created_at"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    total_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"memory": {"floor": 120, "ceiling": 600}, ...}
    section_budgets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    operators: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    deadline_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class ContextBundle(Base):
    __tablename__ = "context_bundle"
    __table_args__ = (
        # `tokens_consumed <= budget` is an invariant, not an estimate. The
        # database refuses to record a bundle that broke it, so a regression
        # cannot quietly become published data.
        CheckConstraint("tokens_consumed <= token_budget", name="budget_not_exceeded"),
        UniqueConstraint("org_id", "digest", name="uq_context_bundle_org_id_digest"),
        Index("ix_context_bundle_org_id_created_at", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_plan.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=True
    )

    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    flow: Mapped[str] = mapped_column(String(32), nullable=False)

    token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_consumed: Mapped[int] = mapped_column(Integer, nullable=False)

    # Per-section spend, admitted/rejected counts, trim events — everything the
    # inspector renders as the "why this and not that" panel.
    budget_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Rejections with reasons: superseded, unauthorized, near-duplicate,
    # conflict-loser, over-budget. Recorded, never silently dropped.
    rejections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    compiled_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    embedder: Mapped[str] = mapped_column(String(128), nullable=False)
    tokenizer: Mapped[str] = mapped_column(String(64), nullable=False)
    compile_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class BundleItem(Base):
    __tablename__ = "bundle_item"
    __table_args__ = (
        CheckConstraint(check_in("operator", OperatorKind), name="operator_valid"),
        UniqueConstraint("bundle_id", "position", name="uq_bundle_item_bundle_id_position"),
        Index("ix_bundle_item_org_id_bundle_id_position", "org_id", "bundle_id", "position"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_bundle.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(32), nullable=False)

    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunk.id", ondelete="SET NULL"), nullable=True
    )
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL"), nullable=True
    )

    text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    rrf_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Calibrated from rank before allocation. Raw fusion scores are nearly flat,
    # and an allocator fed flat scores spends its budget on boilerplate.
    utility: Mapped[float] = mapped_column(Float, nullable=False)
    density: Mapped[float] = mapped_column(Float, nullable=False)

    trust_tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Which authorization decision let this in. Makes a later denial explainable.
    acl_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tag.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
