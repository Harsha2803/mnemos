"""Prompts: versioned in the database, activated without a redeploy.

Prompts are behaviour. Keeping them in source means every wording change is a
build, a deploy, and a rollback window; it also means nobody can tell which
wording produced last Tuesday's bad answer.

Here a prompt has many immutable versions and exactly one active version, held by
a partial unique index. Rolling back is an UPDATE.

`context_bundle` records which version compiled it, so an answer can always be
traced to the exact prompt text that produced it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class Prompt(Base, TimestampMixin):
    __tablename__ = "prompt"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_prompt_org_id_slug"),
        CheckConstraint(
            "kind IN ('system', 'rag', 'nl2sql', 'router', 'agent', 'summarize', 'memory')",
            name="kind_valid",
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class PromptVersion(Base):
    """Immutable once written. Editing a prompt creates a version."""

    __tablename__ = "prompt_version"
    __table_args__ = (
        UniqueConstraint("prompt_id", "version", name="uq_prompt_version_prompt_id_version"),
        # Exactly one active version per prompt, enforced by the database rather
        # than by a service method that everyone remembers to call.
        Index(
            "uq_prompt_version_one_active",
            "prompt_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    # Declared placeholders, checked at save time. A prompt that references a
    # variable the caller never supplies fails at render, which is the worst
    # possible moment to find out.
    variables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)
