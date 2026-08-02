"""Database engine, session lifecycle, and the declarative base.

Two things here are load-bearing beyond boilerplate:

1. **`Base.metadata` is the single target Alembic compares against.** Every model
   module must be imported by `mnemos.platform.models` or its table silently
   disappears from `alembic check`.

2. **Tenant isolation is a database guarantee, not an application one.** Every
   org-scoped table has `FORCE ROW LEVEL SECURITY` and a policy that reads the
   `app.current_org` GUC. `session()` sets that GUC inside the transaction; when
   it is absent the policy compares `org_id` against NULL, which is never true,
   so forgetting to scope a query returns zero rows rather than another tenant's
   rows — the failure mode is an empty page, not a breach.

   Two things make that true rather than aspirational, and both were originally
   missing. The connection must be an *unprivileged* role: RLS does not apply to a
   superuser or to anything holding `BYPASSRLS` (migration `0005`). And the policy
   must read `NULLIF(current_setting(...), '')`, because a reverted `SET LOCAL`
   leaves a placeholder GUC defined as the empty string rather than undefined, and
   `''::uuid` raises instead of yielding NULL (migration `0006`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, ForeignKey, MetaData, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mnemos.core.config import Settings
from mnemos.core.errors import ConfigurationError

# Explicit, deterministic constraint names. Without this, Alembic autogenerate
# emits `op.drop_constraint(None, ...)` for anything the database named itself,
# and the downgrade path is unrunnable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # SQLAlchemy reads this by name; it is a declarative hook, not mutable state.
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        uuid.UUID: UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
        str: Text,
        dict[str, Any]: JSONB,
        list[str]: JSONB,
    }


def pk_column() -> Mapped[uuid.UUID]:
    """Time-ordered primary key. `gen_random_uuid()` is the server-side fallback
    for rows inserted by SQL (seeds, migrations); the application supplies a
    UUIDv7 so keys sort by creation time."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Database:
    """Owns the engine. One instance per process, created at startup."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,  # a recycled connection killed by the server
            pool_recycle=1800,  # must not surface as a request error
            echo=False,
            future=True,
        )
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self, *, org_id: uuid.UUID | None = None) -> AsyncIterator[AsyncSession]:
        """A transaction with the tenant GUC bound to it.

        `set_config(..., is_local => true)` scopes the setting to the transaction,
        so a pooled connection cannot carry one tenant's org into the next
        request that borrows it.
        """
        async with self._sessionmaker() as session, session.begin():
            if org_id is not None:
                await session.execute(
                    text("SELECT set_config('app.current_org', :org, true)"),
                    {"org": str(org_id)},
                )
            yield session

    @asynccontextmanager
    async def elevated_session(self) -> AsyncIterator[AsyncSession]:
        """A transaction that escapes tenant isolation. Two callers, ever.

        `SET LOCAL ROLE` to a role holding `BYPASSRLS`. This exists because
        bootstrap has a genuine chicken-and-egg problem — the first insert creates
        the org that every subsequent row would be scoped to — and because RLS
        makes the alternative silently wrong rather than loudly broken.

        It is a `SET ROLE` rather than a privilege on the application role because
        **role attributes are not inherited through membership**: `mnemos_app` is a
        member of `mnemos_admin` and inherits its table privileges, but not its
        `BYPASSRLS`. Escaping isolation therefore takes a deliberate statement that
        shows up in `pg_stat_activity` and in this method's call sites, instead of
        being the ambient condition of every query.

        `LOCAL` scopes the switch to the transaction, so a pooled connection cannot
        carry the elevation into the next request that borrows it.
        """
        role = self._settings.admin_database_role
        if not role.replace("_", "").isalnum():
            raise ConfigurationError("admin_database_role must be a bare SQL identifier", role=role)
        async with self._sessionmaker() as session, session.begin():
            await session.execute(text(f"SET LOCAL ROLE {role}"))
            yield session

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self._engine.dispose()
