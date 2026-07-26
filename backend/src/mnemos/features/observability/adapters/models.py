"""Observability: the inference ledger and the audit log.

`inference_call` is **range-partitioned by month**. It is the fastest-growing
table in the system and the one nobody wants to keep forever; partitioning makes
retention a `DROP TABLE` on an old partition instead of a `DELETE` that bloats
the heap and blocks vacuum.

Partitioning has a consequence the schema must honour: the partition key has to
be part of every unique constraint, so the primary key is `(id, occurred_at)`
rather than `id` alone.

Cost is recorded even though local inference is free. The number is zero today
and the column is the point: the moment a hosted model is swapped in behind the
same port, the dashboard already works.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.platform.db import Base, org_fk, pk_column


class InferenceCall(Base):
    __tablename__ = "inference_call"
    __table_args__ = (
        CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0", name="tokens_non_negative"
        ),
        Index("ix_inference_call_org_id_occurred_at", "org_id", "occurred_at"),
        Index("ix_inference_call_org_id_model_occurred_at", "org_id", "model", "occurred_at"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    # Composite PK: Postgres requires the partition key in every unique index.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        primary_key=True, server_default=text("now()"), nullable=False
    )

    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)  # generate | embed | rerank

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Zero for self-hosted Ollama. Present so swapping in a paid provider behind
    # the same port needs no schema change.
    cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ok'"))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditLog(Base):
    """Security-relevant events. Append-only, and deliberately not partitioned —
    this one is meant to be kept."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_org_id_occurred_at", "org_id", "occurred_at"),
        Index("ix_audit_log_org_id_action_occurred_at", "org_id", "action", "occurred_at"),
        Index("ix_audit_log_actor_id_occurred_at", "actor_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # user | api_key | system

    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # allow | deny. Denials are the rows that matter; an audit log that only
    # records successes cannot answer the question anyone actually asks.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
