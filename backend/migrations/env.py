"""Alembic environment.

Three things here are deliberate:

* **The URL comes from `Settings`, not from `alembic.ini`.** One source of truth
  means migrations cannot be run against a database the application would reject.
* **`target_metadata` is imported from `mnemos.platform.models`**, which imports
  every model module. Anything it misses, autogenerate would propose to drop.
* **`include_object` hides the monthly partitions of `inference_call`.** They are
  real tables that the model layer does not know about; without this filter every
  autogenerate run would try to delete them.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from mnemos.core.config import get_settings
from mnemos.platform.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def include_object(
    obj: Any, name: str | None, type_: str, _reflected: bool, _compare_to: Any
) -> bool:
    # Partitions are managed by the retention migration, not by autogenerate.
    return not (type_ == "table" and name is not None and name.startswith("inference_call_"))


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        # Every constraint is named by the naming convention in platform.db, so
        # downgrades can drop them by name instead of guessing.
        render_as_batch=False,
        transaction_per_migration=True,
    )


def run_migrations_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
