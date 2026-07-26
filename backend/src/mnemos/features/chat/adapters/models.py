"""Chat: sessions, messages, citations, and the organisational furniture.

A message links to the `context_bundle` that produced it. That link is what makes
the inspector possible: every assistant turn can be opened and explained in terms
of what was actually in the prompt, rather than reconstructed after the fact.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
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

from mnemos.core.types import FeedbackRating, FlowKind, MessageRole, check_in
from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class Folder(Base, TimestampMixin):
    __tablename__ = "folder"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "name", name="uq_folder_org_id_user_id_name"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_session"
    __table_args__ = (
        Index(
            "ix_chat_session_org_id_user_id_last_message_at", "org_id", "user_id", "last_message_at"
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folder.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'New chat'"))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3000"))
    settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (
        CheckConstraint(check_in("role", MessageRole), name="role_valid"),
        UniqueConstraint("session_id", "ordinal", name="uq_chat_message_session_id_ordinal"),
        Index("ix_chat_message_org_id_session_id_ordinal", "org_id", "session_id", "ordinal"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Which pipeline the router chose. Surfaced in the UI so the routing decision
    # is visible instead of mysterious.
    flow: Mapped[str | None] = mapped_column(String(32), nullable=True)
    router_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    router_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The prompt that produced this message, byte for byte.
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_bundle.id", ondelete="SET NULL"), nullable=True
    )

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    msg_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class MessageCitation(Base):
    """A citation resolves to a character span, not to a document name.

    Offsets are copied rather than joined through the chunk, because a chunk can
    be re-chunked by a later ingest and the citation must still point at what the
    model was actually shown.
    """

    __tablename__ = "message_citation"
    __table_args__ = (
        UniqueConstraint("message_id", "marker", name="uq_message_citation_message_id_marker"),
        Index("ix_message_citation_org_id_message_id", "org_id", "message_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False
    )
    marker: Mapped[int] = mapped_column(Integer, nullable=False)

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL"), nullable=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunk.id", ondelete="SET NULL"), nullable=True
    )
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory.id", ondelete="SET NULL"), nullable=True
    )

    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class Bookmark(Base, TimestampMixin):
    __tablename__ = "bookmark"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_bookmark_user_id_message_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_feedback_user_id_message_id"),
        CheckConstraint(check_in("rating", FeedbackRating), name="rating_valid"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


# Re-exported so the enum used by the router is discoverable from this module,
# which is where a reader looking at `chat_message.flow` will land first.
__all__ = [
    "Bookmark",
    "ChatMessage",
    "ChatSession",
    "Feedback",
    "FlowKind",
    "Folder",
    "MessageCitation",
]
