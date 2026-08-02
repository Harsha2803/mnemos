"""Tenant isolation, proved against a real Postgres.

Constraint C1 of the threat model is that a cross-tenant read is the one bug that
ends the project. The defences are meant to be independent: an explicit `org_id`
filter in every query, and row-level security underneath it. This file tests the
*second* one, on purpose, with queries that deliberately omit the first — because
a test that filters by `org_id` proves only that `WHERE` works.

Migration `0004` enabled the policies. It was necessary and not sufficient: RLS
never applies to a superuser or to a `BYPASSRLS` role, and until migration `0005`
the application connected as a superuser, so every policy was inert.
`test_application_role_holds_no_rls_exemption` is the guard against that
regression returning — a permission error is very tempting to "fix" by pointing
the DSN back at the owner, and doing so silently disables tenant isolation
everywhere while leaving all the policies visible in the catalogue.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from mnemos.core.ids import uuid7
from mnemos.platform.models import ORG_SCOPED_TABLES, Base

from .conftest import Postgres

ORG_A_SLUG = "isolation-org-a"
ORG_B_SLUG = "isolation-org-b"


@pytest_asyncio.fixture
async def orgs(postgres: Postgres) -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    """Two orgs, each with one `tag` row, written as the owner.

    Seeding as the owner is the point: it is the only role that can put another
    tenant's row in the table, which is what gives the application role something
    it must not see.
    """
    org_a, org_b = uuid7(), uuid7()
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        for org_id, slug in ((org_a, ORG_A_SLUG), (org_b, ORG_B_SLUG)):
            await conn.execute(
                "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)", org_id, slug, slug
            )
            await conn.execute(
                "INSERT INTO tag (id, org_id, slug, name) VALUES ($1, $2, $3, $4)",
                uuid7(),
                org_id,
                f"tag-{slug}",
                f"Tag for {slug}",
            )
        yield org_a, org_b
        await conn.execute("DELETE FROM org WHERE id = ANY($1::uuid[])", [org_a, org_b])
    finally:
        await conn.close()


async def _app_connection(postgres: Postgres) -> asyncpg.Connection:
    return await asyncpg.connect(postgres.app_dsn)


async def test_cross_org_read_returns_zero_rows(
    postgres: Postgres, orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """The same unfiltered query, run under two tenants, returns disjoint rows.

    `SELECT ... FROM tag` carries no `org_id` predicate at all. Every row the two
    tenants see is therefore attributable to the policy and to nothing in the
    application.
    """
    org_a, org_b = orgs
    conn = await _app_connection(postgres)
    try:
        seen: dict[uuid.UUID, set[uuid.UUID]] = {}
        for org_id in (org_a, org_b):
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.current_org', $1, true)", str(org_id))
                rows = await conn.fetch("SELECT org_id FROM tag")
            seen[org_id] = {row["org_id"] for row in rows}

        assert seen[org_a] == {org_a}, "org A saw rows it does not own"
        assert seen[org_b] == {org_b}, "org B saw rows it does not own"
        assert org_b not in seen[org_a]
        assert org_a not in seen[org_b]
    finally:
        await conn.close()


async def test_unscoped_read_returns_zero_rows_rather_than_raising(
    postgres: Postgres, orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Forgetting to scope yields an empty page, on a reused connection too.

    This is the case migration `0006` exists for. `set_config(..., is_local =>
    true)` reverts at commit, but a dot-qualified placeholder GUC that has been
    assigned once stays *defined as the empty string* rather than becoming
    undefined — so the original `current_setting(...)::uuid` raised `22P02` on
    every pooled connection that had already served a scoped request. Intermittent,
    load-dependent, and invisible to any test that used a fresh connection.
    """
    org_a, _ = orgs
    conn = await _app_connection(postgres)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_org', $1, true)", str(org_a))
            scoped = await conn.fetch("SELECT org_id FROM tag")
        assert len(scoped) == 1

        # Same connection, GUC now reverted to ''. Must be empty, not an error.
        unscoped = await conn.fetch("SELECT org_id FROM tag")
        assert unscoped == []
    finally:
        await conn.close()


async def test_cross_org_write_is_rejected(
    postgres: Postgres, orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """A write naming another tenant fails the policy's WITH CHECK.

    Read isolation alone would let a compromised or buggy caller plant rows in
    another tenant, which is the same breach arriving from the other direction.
    """
    org_a, org_b = orgs
    conn = await _app_connection(postgres)

    async def smuggle() -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_org', $1, true)", str(org_a))
            await conn.execute(
                "INSERT INTO tag (id, org_id, slug, name) VALUES ($1, $2, $3, $4)",
                uuid7(),
                org_b,
                "smuggled",
                "Smuggled",
            )

    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await smuggle()
    finally:
        await conn.close()


async def test_application_role_holds_no_rls_exemption(postgres: Postgres) -> None:
    """The role the application connects as must not be able to bypass a policy.

    Asserted on the live connection rather than on configuration, because the
    regression this guards against is a change to a DSN — and a DSN is the one
    thing no amount of correct SQL protects you from.
    """
    conn = await _app_connection(postgres)
    try:
        row = await conn.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        assert row is not None
        assert row["rolsuper"] is False, "the application connects as a superuser; RLS is inert"
        assert row["rolbypassrls"] is False, "the application role holds BYPASSRLS; RLS is inert"
    finally:
        await conn.close()


async def test_every_org_scoped_table_has_forced_rls(postgres: Postgres) -> None:
    """`ORG_SCOPED_TABLES` and the live catalogue agree, in both directions.

    A table added to `Base.metadata` with an `org_id` column but not to
    `ORG_SCOPED_TABLES` gets no policy, and the omission is invisible: queries
    keep working, and they work across tenants. Checking the reverse direction too
    means the list cannot drift into naming tables that no longer exist.
    """
    conn = await _app_connection(postgres)
    try:
        rows = await conn.fetch(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
            """
        )
    finally:
        await conn.close()

    live = {row["relname"]: row for row in rows}

    for table in ORG_SCOPED_TABLES:
        assert table in live, f"{table} is listed as org-scoped but does not exist"
        assert live[table]["relrowsecurity"], f"{table} has no row-level security"
        assert live[table]["relforcerowsecurity"], (
            f"{table} has RLS enabled but not FORCEd, so it does not apply to the owner"
        )

    declared = set(ORG_SCOPED_TABLES)
    modelled = {
        table.name
        for table in Base.metadata.tables.values()
        if "org_id" in table.columns and table.name != "org"
    }
    assert modelled - declared == set(), (
        "these tables carry org_id but are missing from ORG_SCOPED_TABLES, "
        "so they have no isolation policy"
    )
