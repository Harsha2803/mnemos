"""`mnemosctl connector register` is documented as idempotent per slug — a
regression test for the bug D1's deterministic demo-seed work found: the CLI
relied on `uq_content_source_org_id_slug` alone and let a duplicate-slug
retry crash with a raw `IntegrityError` traceback instead of the friendly
"already present" `mnemosctl bootstrap` itself uses. `test_connectors_router.py`
already pins the *API*'s translation of that same constraint into a 409 for a
browser caller; this pins the CLI's own contract, which is different — a
retry is the normal shape of a re-run seed script, not a conflict.
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from pydantic import SecretStr

import mnemos.entrypoints.cli as cli_module
from mnemos.core.config import Settings
from mnemos.core.ids import DEFAULT_ID_GENERATOR, uuid7
from mnemos.entrypoints.cli import _connector_register
from mnemos.features.connectors.adapters.repository import ContentSourceRepository
from mnemos.features.identity.domain import OrgId
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SOURCE_KEY = "zyE7WKGQXXwuWC7pvMVZ3qbkXUliL3BRmD8Lzk89qu4="


@pytest_asyncio.fixture
async def org(postgres: Postgres) -> AsyncIterator[OrgId]:
    org_id = OrgId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            org_id,
            "cli-cr-org",
            "cli-cr-org",
        )
        yield org_id
        await conn.execute("DELETE FROM org WHERE id = $1", org_id)
    finally:
        await conn.close()


def _args(slug: str, root: str) -> argparse.Namespace:
    return argparse.Namespace(
        org_slug="cli-cr-org",
        slug=slug,
        name="CLI demo source",
        kind="local_fs",
        bucket=None,
        prefix=None,
        root=root,
        url=None,
    )


async def test_registering_the_same_slug_twice_succeeds_both_times(
    postgres: Postgres, org: OrgId, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        env="test",  # type: ignore[arg-type]
        database_url=postgres.app_url,
        app_database_password=APP_PASSWORD,  # type: ignore[arg-type]
        source_encryption_key=SecretStr(SOURCE_KEY),
        local_fs_allowed_roots=[str(tmp_path)],
    )
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)

    args = _args("cli-idempotent-slug", str(tmp_path))
    first = await _connector_register(args)
    second = await _connector_register(args)

    assert first == 0
    assert second == 0

    db = Database(settings)
    try:
        repository = ContentSourceRepository(db, DEFAULT_ID_GENERATOR)
        record = await repository.get_by_slug(org_id=org, slug="cli-idempotent-slug")
        assert record is not None
    finally:
        await db.dispose()
