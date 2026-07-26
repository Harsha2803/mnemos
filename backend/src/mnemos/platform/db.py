"""Database engine, session lifecycle, and the declarative base.

Two things here are load-bearing beyond boilerplate:

1. **`Base.metadata` is the single target Alembic compares against.** Every model
   module must be imported by `mnemos.platform.models` or its table silently
   disappears from `alembic check`.

2. **Tenant isolation is a database guarantee, not an application one.** Every
   org-scoped table has `FORCE ROW LEVEL SECURITY` and a policy that reads the
   `app.current_org` GUC. `session_scope` sets that GUC inside the transaction;
   if it is never set, `current_setting(..., true)` yields NULL and the policy
   matches nothing. Forgetting to scope a query returns zero rows rather than
   another tenant's rows — the failure mode is an empty page, not a breach.
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

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self._engine.dispose()
