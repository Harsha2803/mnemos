"""Shared fixtures.

The Postgres fixture is deliberately heavy: a real container, the real
extensions, and the real Alembic revisions applied in order. Tenant isolation is
a property of Postgres row-level security, so a fake or an in-memory substitute
would only prove that the substitute isolates. The same argument covers the role
split — `mnemos_app` is created by migration `0005`, so the only way to test that
the application role is genuinely unprivileged is to let the migration create it.

The container is session-scoped because starting it costs ~15s and the tests that
use it are read-mostly. It is a synchronous fixture that drives async setup
through `asyncio.run`, rather than a session-scoped async fixture, so it does not
have to share an event loop with the function-scoped tests that consume it.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
from testcontainers.community.postgres import PostgresContainer

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Created by `deploy/postgres/init/01-extensions.sql` in the compose stack, which
# runs as superuser because `CREATE EXTENSION` requires it. The test fixture has
# to do the same thing for the same reason: migration `0001` assumes they exist.
EXTENSIONS = ("vector", "pg_trgm", "btree_gist", "citext", '"uuid-ossp"')

OWNER_USER = "mnemos"
OWNER_PASSWORD = "mnemos"
DATABASE = "mnemos"
APP_PASSWORD = "app-role-test-only"


@dataclass(frozen=True)
class Postgres:
    """Connection URLs for the two roles the platform uses.

    `owner_url` is the superuser that owns the tables and runs migrations.
    `app_url` is `mnemos_app`: NOSUPERUSER, NOBYPASSRLS, DML only. RLS applies to
    the second and cannot apply to the first.
    """

    host: str
    port: int

    def _url(self, user: str, password: str, *, driver: str) -> str:
        sep = "+" + driver if driver else ""
        return f"postgresql{sep}://{user}:{password}@{self.host}:{self.port}/{DATABASE}"

    @property
    def owner_url(self) -> str:
        return self._url(OWNER_USER, OWNER_PASSWORD, driver="asyncpg")

    @property
    def app_url(self) -> str:
        return self._url("mnemos_app", APP_PASSWORD, driver="asyncpg")

    @property
    def owner_dsn(self) -> str:
        return self._url(OWNER_USER, OWNER_PASSWORD, driver="")

    @property
    def app_dsn(self) -> str:
        return self._url("mnemos_app", APP_PASSWORD, driver="")


async def _create_extensions(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        for extension in EXTENSIONS:
            await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    finally:
        await conn.close()


def _run_migrations(owner_url: str) -> None:
    """Apply every revision as the owning role, exactly as the `migrate` service does.

    Invoked as a subprocess rather than through `alembic.command` because
    `migrations/env.py` reads an `lru_cache`d `Settings`. Driving it in-process
    would mean either mutating that cache or accepting whichever URL the first
    test to import it happened to bind.
    """
    env = {
        **os.environ,
        "MNEMOS_ENV": "test",
        "MNEMOS_DATABASE_URL": owner_url,
        "MNEMOS_APP_DATABASE_PASSWORD": APP_PASSWORD,
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="session")
def postgres() -> Iterator[Postgres]:
    container = PostgresContainer(
        "pgvector/pgvector:pg16",
        username=OWNER_USER,
        password=OWNER_PASSWORD,
        dbname=DATABASE,
        # No driver in the URL: nothing here connects through a sync DBAPI, and
        # asking for one would make psycopg2 a dependency of the test suite.
        driver=None,
    )
    with container:
        pg = Postgres(
            host=container.get_container_host_ip(), port=int(container.get_exposed_port(5432))
        )
        asyncio.run(_create_extensions(pg.owner_dsn))
        _run_migrations(pg.owner_url)
        yield pg
