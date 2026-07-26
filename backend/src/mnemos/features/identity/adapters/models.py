"""Identity: orgs, users, roles, tags, API keys, external providers, sessions.

Two decisions worth naming:

*Tags, not per-document ACL rows.* Authorization is expressed as tags on users
and tags on documents. That keeps the predicate a set-overlap test, which is the
only reason the retrieval scan can push authorization down into the SQL WHERE
clause instead of filtering after the fact.

*Roles are bound, not assigned.* `role_binding` carries an optional scope so the
same role can mean "admin of this org" or, later, "editor of this collection"
without a second table.
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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.core.types import ProviderKind, check_in
from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class Org(Base, TimestampMixin):
    __tablename__ = "org"

    id: Mapped[uuid.UUID] = pk_column()
    slug: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class AppUser(Base, TimestampMixin):
    """`app_user`, not `user` — `user` is a reserved word in Postgres and an
    unquoted reference to it silently resolves to the session role."""

    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_app_user_org_id_email"),
        Index("ix_app_user_org_id_external_subject", "org_id", "external_subject"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)

    # Null for users that exist only in an external IdP. Argon2id; never bcrypt,
    # never a fast hash.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_provider.id", ondelete="SET NULL"), nullable=True
    )
    external_subject: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)


class IdentityProvider(Base, TimestampMixin):
    """One row per configured authentication protocol.

    The Strategy + Factory split lives in `features/identity/providers/`; this
    table is what the factory reads to decide which strategy to construct. Adding
    SAML later is a row plus an adapter, not a change to the login endpoint.
    """

    __tablename__ = "identity_provider"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_identity_provider_org_id_slug"),
        CheckConstraint(check_in("kind", ProviderKind), name="kind_valid"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # Split-horizon OIDC lives here: the browser is redirected to
    # `issuer_public`, the API validates `iss` and fetches JWKS from
    # `issuer_internal`. One URL for both is the classic containerised failure.
    issuer_public: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer_internal: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class Role(Base, TimestampMixin):
    __tablename__ = "role"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_role_org_id_slug"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Flat list of `resource:action` strings. Checked with set membership at the
    # boundary; deny is the default for anything absent.
    permissions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class RoleBinding(Base, TimestampMixin):
    __tablename__ = "role_binding"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "role_id", "scope", name="uq_role_binding_user_id_role_id_scope"
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("role.id", ondelete="CASCADE"), nullable=False
    )
    # '*' means org-wide. A future collection-scoped binding needs no new table.
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'*'"))


class Tag(Base, TimestampMixin):
    """The unit of document authorization."""

    __tablename__ = "tag"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_tag_org_id_slug"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserTag(Base, TimestampMixin):
    __tablename__ = "user_tag"
    __table_args__ = (UniqueConstraint("user_id", "tag_id", name="uq_user_tag_user_id_tag_id"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE"), nullable=False, index=True
    )


class ApiKey(Base, TimestampMixin):
    """Machine credentials.

    Only the hash is stored, and the plaintext is shown exactly once at creation.
    `prefix` exists so a key can be identified in a list and in audit logs
    without the secret ever being retrievable.
    """

    __tablename__ = "api_key"
    __table_args__ = (UniqueConstraint("key_hash", name="uq_api_key_key_hash"),)

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Session(Base, TimestampMixin):
    """Refresh-token family.

    The refresh token is stored hashed and rotated on every use. `rotated_to`
    turns the family into a chain, so presenting a token that has already been
    rotated proves theft and the whole family is revoked.
    """

    __tablename__ = "session"
    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_session_refresh_token_hash"),
        Index("ix_session_user_id_expires_at", "user_id", "expires_at"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    rotated_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session.id", ondelete="SET NULL"), nullable=True
    )
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
