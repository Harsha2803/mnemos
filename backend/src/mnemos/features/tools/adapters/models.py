"""Tools: the MCP registry, per-user credentials, grants, and the call log.

Three things a tool runtime gets wrong if it is not designed for them up front:

*Credentials are per user, not per server.* A shared service account means every
user's tool calls carry every user's authority. `mcp_credential` is keyed on
(server, user).

*Approval is a state, not a callback.* An invocation that needs a human sits in
`pending_approval` in the database, so an approval survives a restart and is
auditable afterwards.

*Denials must be explainable.* `denied_reason` plus `offending_bundle_item_id`
means "this tool call was blocked because a retrieved document tried to trigger
it" is something the UI can actually say.
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
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.core.types import InvocationStatus, check_in
from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class McpServer(Base, TimestampMixin):
    __tablename__ = "mcp_server"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_mcp_server_org_id_slug"),
        CheckConstraint("transport IN ('stdio', 'http', 'sse')", name="transport_valid"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # A tool may only be invoked by context at or above this tier. Retrieved
    # document text sits at the bottom, so a document cannot call a tool.
    min_trust_tier: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("20")
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    acl_tag_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    last_discovered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    health_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class McpTool(Base, TimestampMixin):
    """Discovered from the server, cached here so the tool list does not require
    a round trip on every turn."""

    __tablename__ = "mcp_tool"
    __table_args__ = (
        UniqueConstraint("server_id", "name", name="uq_mcp_tool_server_id_name"),
        Index("ix_mcp_tool_org_id_server_id", "org_id", "server_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_server.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # A read-only tool can run unattended; a mutating one cannot.
    is_mutating: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class McpCredential(Base, TimestampMixin):
    """One secret per (server, user). Never a shared service account."""

    __tablename__ = "mcp_credential"
    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_mcp_credential_server_id_user_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_server.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheme: Mapped[str] = mapped_column(String(32), nullable=False)
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class McpGrant(Base, TimestampMixin):
    """Standing permission for a user to call a tool. Absent means denied."""

    __tablename__ = "mcp_grant"
    __table_args__ = (UniqueConstraint("tool_id", "user_id", name="uq_mcp_grant_tool_id_user_id"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_tool.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    auto_approve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class McpInvocation(Base):
    __tablename__ = "mcp_invocation"
    __table_args__ = (
        CheckConstraint(check_in("status", InvocationStatus), name="status_valid"),
        Index("ix_mcp_invocation_org_id_created_at", "org_id", "created_at"),
        Index(
            "ix_mcp_invocation_status_created_at",
            "status",
            "created_at",
            postgresql_where=text("status = 'pending_approval'"),
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_tool.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=True
    )

    arguments: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # The tier of the context that asked for this call, and — when it was blocked
    # — exactly which context item was responsible.
    caller_trust_tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    denied_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    offending_bundle_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bundle_item.id", ondelete="SET NULL"), nullable=True
    )

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    result: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
