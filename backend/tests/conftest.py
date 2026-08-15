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
from testcontainers.community.redis import RedisContainer

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Created by `deploy/postgres/init/01-extensions.sql` in the compose stack, which
# runs as superuser because `CREATE EXTENSION` requires it. The test fixture has
# to do the same thing for the same reason: migration `0001` assumes they exist.
EXTENSIONS = ("vector", "pg_trgm", "btree_gist", "citext", '"uuid-ossp"')

OWNER_USER = "mnemos"
OWNER_PASSWORD = "mnemos"
DATABASE = "mnemos"
APP_PASSWORD = "app-role-test-only"

# The NL2SQL warehouse: a second database on the same container, seeded from the
# same SQL the compose stack runs at `deploy/postgres/init/02-analytics-seed.sql`
# — a fake warehouse would only prove the fake is introspectable, and the point
# of `mnemos_ro` is that it is a real Postgres role that physically cannot write.
ANALYTICS_DATABASE = "mnemos_analytics"
ANALYTICS_RO_USER = "mnemos_ro"
ANALYTICS_RO_PASSWORD = "mnemos_ro_dev"


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

    def _analytics_url(self, user: str, password: str, *, driver: str) -> str:
        sep = "+" + driver if driver else ""
        return f"postgresql{sep}://{user}:{password}@{self.host}:{self.port}/{ANALYTICS_DATABASE}"

    @property
    def analytics_owner_dsn(self) -> str:
        return self._analytics_url(OWNER_USER, OWNER_PASSWORD, driver="")

    @property
    def analytics_ro_url(self) -> str:
        return self._analytics_url(ANALYTICS_RO_USER, ANALYTICS_RO_PASSWORD, driver="asyncpg")

    @property
    def analytics_ro_dsn(self) -> str:
        return self._analytics_url(ANALYTICS_RO_USER, ANALYTICS_RO_PASSWORD, driver="")


async def _create_extensions(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        for extension in EXTENSIONS:
            await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    finally:
        await conn.close()


async def _seed_analytics_warehouse(pg: Postgres) -> None:
    """Create `mnemos_analytics` and run the real seed script against it.

    The seed script is written for `psql` (it opens with `\\connect
    mnemos_analytics`, a client meta-command asyncpg does not understand)
    against a database that does not exist yet — `CREATE DATABASE` cannot run
    inside the transaction `execute()` would otherwise wrap it in, so it is a
    separate connection and a separate statement, and only then does the seed
    script run against the database it just created.
    """
    owner_conn = await asyncpg.connect(pg.owner_dsn)
    try:
        await owner_conn.execute(f"CREATE DATABASE {ANALYTICS_DATABASE}")
    finally:
        await owner_conn.close()

    sql_path = BACKEND_ROOT.parent / "deploy" / "postgres" / "init" / "02-analytics-seed.sql"
    statements = "\n".join(
        line for line in sql_path.read_text().splitlines() if not line.strip().startswith("\\")
    )

    analytics_conn = await asyncpg.connect(pg.analytics_owner_dsn)
    try:
        await analytics_conn.execute(statements)
    finally:
        await analytics_conn.close()


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
        asyncio.run(_seed_analytics_warehouse(pg))
        yield pg


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """A real Redis, for the same reason `postgres` above is real: consumer-
    group durability (`platform/events/redis_streams.py`) is a property of
    actual Redis Streams, and a fake would only prove the fake is durable."""
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"
