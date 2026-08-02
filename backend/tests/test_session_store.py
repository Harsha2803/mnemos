"""M3.4 — the session store's SQL, against a real Postgres.

`test_refresh_rotation.py` proves the *policy* against in-memory fakes and says
so. This file exists because two of the things that policy depends on are
properties of the database rather than of our code, and a fake would only prove
the fake:

1. **The recursive walk.** `session.rotated_to` is a forward pointer, so reaching
   a whole chain from an arbitrary member means walking both directions in one
   statement. The Python equivalent in the fake is a breadth-first search that
   nobody ships.
2. **The compare-and-set.** "Two concurrent rotations of one token cannot both
   succeed" is a claim about row locking and transaction isolation. Asserting it
   requires two real concurrent transactions against a real server.

Plus the thing every M3 test has to keep honest: **the store never escapes its
tenant.** It runs as `mnemos_app` (NOSUPERUSER, NOBYPASSRLS) with the
`app.current_org` GUC bound by `Database.session()`, so the row-level security
from migrations `0004`-`0006` is underneath every statement here.

Session-scoped container, shared with `test_tenant_isolation.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import Row
from sqlalchemy import text as sql

from mnemos.core.config import Settings
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.features.identity.adapters.sessions import SqlAppUserStore, SqlSessionStore
from mnemos.features.identity.application.tokens import REVOKED_BY_REUSE
from mnemos.features.identity.domain import OrgId, ProviderId, SessionId, UserId
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

ORG_A_SLUG = "session-store-org-a"
ORG_B_SLUG = "session-store-org-b"

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=14)


class Seed(NamedTuple):
    """What the fixture wrote. Named, because `seeded[3]` in six tests is how a
    test ends up asserting about the wrong tenant without anyone noticing."""

    org_a: OrgId
    user_a: UserId
    provider_a: ProviderId
    org_b: OrgId
    user_b: UserId


@pytest.fixture(scope="module")
def ids() -> Uuid7Generator:
    return Uuid7Generator()


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    """Two orgs, each with one user and one enabled OIDC provider row.

    Seeded as the owner for the reason `test_tenant_isolation.py` gives: it is
    the only role that can put another tenant's row in the table, which is what
    gives the application role something it must not see.

    The `identity_provider` row is not decoration — `app_user.provider_id` is a
    foreign key, so provisioning against an invented provider id is an
    `IntegrityError` rather than a user. That is the constraint doing its job:
    a provisioned user must be attributable to the provider that vouched for it.
    """
    org_a, org_b = OrgId(uuid7()), OrgId(uuid7())
    user_a, user_b = UserId(uuid7()), UserId(uuid7())
    provider_a, provider_b = ProviderId(uuid7()), ProviderId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        for org_id, slug, user_id, provider_id in (
            (org_a, ORG_A_SLUG, user_a, provider_a),
            (org_b, ORG_B_SLUG, user_b, provider_b),
        ):
            await conn.execute(
                "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)", org_id, slug, slug
            )
            await conn.execute(
                "INSERT INTO identity_provider (id, org_id, slug, kind, display_name) "
                "VALUES ($1, $2, 'keycloak', 'oidc', 'Keycloak')",
                provider_id,
                org_id,
            )
            await conn.execute(
                "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
                user_id,
                org_id,
                f"user@{slug}.test",
                slug,
            )
        yield Seed(org_a, user_a, provider_a, org_b, user_b)
        await conn.execute("DELETE FROM org WHERE id = ANY($1::uuid[])", [org_a, org_b])
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db(postgres: Postgres) -> AsyncIterator[Database]:
    """A `Database` on the **unprivileged** role, so RLS applies to it."""
    database = Database(
        Settings(
            env="test",  # type: ignore[arg-type]
            database_url=postgres.app_url,
            app_database_password=APP_PASSWORD,  # type: ignore[arg-type]
        )
    )
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def sessions(db: Database, ids: Uuid7Generator) -> SqlSessionStore:
    return SqlSessionStore(db, ids)


@pytest.fixture
def users(db: Database, ids: Uuid7Generator) -> SqlAppUserStore:
    return SqlAppUserStore(db, ids)


async def _open(
    store: SqlSessionStore, org_id: OrgId, user_id: UserId, token_hash: str
) -> SessionId:
    return await store.open(
        org_id=org_id,
        user_id=user_id,
        token_hash=token_hash,
        issued_at=NOW,
        expires_at=LATER,
        user_agent="pytest",
        ip_address="127.0.0.1",
    )


async def _rotate(
    store: SqlSessionStore, org_id: OrgId, predecessor: SessionId, token_hash: str
) -> SessionId | None:
    return await store.rotate(
        org_id=org_id,
        predecessor=predecessor,
        token_hash=token_hash,
        issued_at=NOW,
        expires_at=LATER,
        user_agent="pytest",
        ip_address="127.0.0.1",
    )


async def _chain(
    store: SqlSessionStore, org_id: OrgId, user_id: UserId, links: int
) -> list[SessionId]:
    """A rotation chain `links` long, through the real statements."""
    chain = [await _open(store, org_id, user_id, f"hash-{uuid.uuid4()}")]
    for _ in range(links - 1):
        successor = await _rotate(store, org_id, chain[-1], f"hash-{uuid.uuid4()}")
        assert successor is not None
        chain.append(successor)
    return chain


# ------------------------------------------------------------------ the control


async def test_a_session_round_trips_through_the_real_table(
    sessions: SqlSessionStore, seeded: Seed
) -> None:
    """Every assertion below is one mutation away from this."""
    org_a, user_a = seeded.org_a, seeded.user_a
    token_hash = f"hash-{uuid.uuid4()}"
    session_id = await _open(sessions, org_a, user_a, token_hash)

    found = await sessions.find_by_token_hash(org_a, token_hash)
    assert found is not None
    assert found.session_id == session_id
    assert found.org_id == org_a
    assert found.user_id == user_a
    assert found.refresh_token_hash == token_hash
    assert found.rotated_to is None
    assert found.revoked_at is None
    assert found.expires_at == LATER


async def test_a_session_is_invisible_to_another_org(
    sessions: SqlSessionStore, seeded: Seed
) -> None:
    """Even knowing the exact hash. The explicit `org_id` predicate and the RLS
    policy are two independent reasons this returns nothing, which is the point
    of having both (CodingStandards §6)."""
    org_a, user_a, org_b = seeded.org_a, seeded.user_a, seeded.org_b
    token_hash = f"hash-{uuid.uuid4()}"
    await _open(sessions, org_a, user_a, token_hash)

    assert await sessions.find_by_token_hash(org_b, token_hash) is None


# --------------------------------------------------------- rotation, for real


async def test_rotate_records_the_successor_on_the_predecessor(
    sessions: SqlSessionStore, seeded: Seed
) -> None:
    org_a, user_a = seeded.org_a, seeded.user_a
    first_hash, second_hash = f"hash-{uuid.uuid4()}", f"hash-{uuid.uuid4()}"
    first = await _open(sessions, org_a, user_a, first_hash)
    second = await _rotate(sessions, org_a, first, second_hash)

    assert second is not None
    predecessor = await sessions.find_by_token_hash(org_a, first_hash)
    assert predecessor is not None
    assert predecessor.rotated_to == second

    successor = await sessions.find_by_token_hash(org_a, second_hash)
    assert successor is not None
    assert successor.rotated_to is None
    # The successor inherits the predecessor's owner, read inside the same
    # transaction rather than carried in by the caller.
    assert successor.user_id == user_a


async def test_rotating_an_already_rotated_session_leaves_no_orphan(
    sessions: SqlSessionStore, seeded: Seed
) -> None:
    """The compare-and-set fails *after* the successor row has been inserted, so
    the transaction has to take that row back with it. An orphaned session row is
    a live refresh token nobody's chain points at."""
    org_a, user_a = seeded.org_a, seeded.user_a
    first = await _open(sessions, org_a, user_a, f"hash-{uuid.uuid4()}")
    assert await _rotate(sessions, org_a, first, f"hash-{uuid.uuid4()}") is not None

    orphan_hash = f"hash-{uuid.uuid4()}"
    assert await _rotate(sessions, org_a, first, orphan_hash) is None
    assert await sessions.find_by_token_hash(org_a, orphan_hash) is None, (
        "the rolled-back successor must not survive"
    )


async def test_two_concurrent_rotations_of_one_token_cannot_both_win(
    sessions: SqlSessionStore, seeded: Seed
) -> None:
    """The claim that only a real database can settle.

    Both transactions read a row with `rotated_to IS NULL`. The conditional
    UPDATE takes a row lock, so the second blocks until the first commits and
    then matches nothing. A read-then-write would let both through and produce
    two live chains from one credential — the exact state the family kill exists
    to make impossible.
    """
    org_a, user_a = seeded.org_a, seeded.user_a
    first = await _open(sessions, org_a, user_a, f"hash-{uuid.uuid4()}")
    hashes = [f"hash-{uuid.uuid4()}", f"hash-{uuid.uuid4()}"]

    outcomes = await asyncio.gather(
        _rotate(sessions, org_a, first, hashes[0]),
        _rotate(sessions, org_a, first, hashes[1]),
    )

    winners = [o for o in outcomes if o is not None]
    assert len(winners) == 1, f"exactly one rotation may win, got {outcomes}"
    survivors = [h for h in hashes if await sessions.find_by_token_hash(org_a, h) is not None]
    assert len(survivors) == 1, "the loser's successor row was not rolled back"


# ------------------------------------------------------------ the family walk


async def test_revoke_family_reaches_the_whole_chain_from_any_member(
    sessions: SqlSessionStore, db: Database, seeded: Seed
) -> None:
    """The recursive CTE, which is the whole reason this file needs Postgres.

    Revoking from a *middle* link has to reach ancestors (`s.id = f.rotated_to`)
    and descendants (`s.rotated_to = f.id`) alike. A walk that only followed the
    forward pointer would leave every earlier token in the chain live, and those
    are exactly the ones a thief is holding.
    """
    org_a, user_a = seeded.org_a, seeded.user_a
    chain = await _chain(sessions, org_a, user_a, links=5)

    revoked = await sessions.revoke_family(
        org_id=org_a, member=chain[2], reason=REVOKED_BY_REUSE, at=NOW
    )

    assert set(revoked) == set(chain), "the walk did not reach the whole chain"
    for session_id in chain:
        row = await _row(db, org_a, session_id)
        assert row.revoked_at is not None
        assert row.revoked_reason == REVOKED_BY_REUSE


async def test_revoke_family_is_idempotent_and_does_not_restamp(
    sessions: SqlSessionStore, db: Database, seeded: Seed
) -> None:
    """`WHERE revoked_at IS NULL` means a second call reports nothing and leaves
    the original reason in place — so a sign-out following a reuse detection does
    not overwrite the evidence."""
    org_a, user_a = seeded.org_a, seeded.user_a
    chain = await _chain(sessions, org_a, user_a, links=3)

    first_pass = await sessions.revoke_family(
        org_id=org_a, member=chain[0], reason=REVOKED_BY_REUSE, at=NOW
    )
    second_pass = await sessions.revoke_family(
        org_id=org_a, member=chain[0], reason="signed_out", at=NOW + timedelta(hours=1)
    )

    assert len(first_pass) == 3
    assert second_pass == []
    assert (await _row(db, org_a, chain[1])).revoked_reason == REVOKED_BY_REUSE


async def test_revoke_family_does_not_touch_a_sibling_chain(
    sessions: SqlSessionStore, db: Database, seeded: Seed
) -> None:
    """One user, two devices. Signing out of one must not sign out the other,
    and the two chains are only distinguishable by the pointer."""
    org_a, user_a = seeded.org_a, seeded.user_a
    laptop = await _chain(sessions, org_a, user_a, links=3)
    phone = await _chain(sessions, org_a, user_a, links=3)

    await sessions.revoke_family(org_id=org_a, member=laptop[1], reason="signed_out", at=NOW)

    assert [(await _row(db, org_a, s)).revoked_at for s in laptop] == [NOW] * 3
    assert [(await _row(db, org_a, s)).revoked_at for s in phone] == [None] * 3


async def test_revoke_family_cannot_cross_a_tenant_boundary(
    sessions: SqlSessionStore, db: Database, seeded: Seed
) -> None:
    """Naming another org's session revokes nothing — and, because the walk runs
    under that org's GUC, cannot even see it to try."""
    org_a, org_b, user_b = seeded.org_a, seeded.org_b, seeded.user_b
    theirs = await _chain(sessions, org_b, user_b, links=3)

    revoked = await sessions.revoke_family(
        org_id=org_a, member=theirs[0], reason=REVOKED_BY_REUSE, at=NOW
    )

    assert revoked == []
    assert [(await _row(db, org_b, s)).revoked_at for s in theirs] == [None] * 3


# ------------------------------------------------------ provisioning, for real


async def test_provisioning_writes_no_password_hash_and_grants_no_role(
    users: SqlAppUserStore,
    db: Database,
    seeded: Seed,
) -> None:
    """The two halves of "identity, never authority", asserted against the rows.

    `password_hash IS NULL` is what stops a JIT-provisioned user password-
    authenticating (M3.2 refuses a row with no hash). Zero `role_binding` rows is
    what stops them doing anything at all until M3.6 grants something.
    """
    org_a = seeded.org_a
    created = await users.create(
        org_id=org_a,
        provider_id=seeded.provider_a,
        external_subject="a-keycloak-subject",
        email="provisioned@example.test",
        display_name="Provisioned Person",
    )

    async with db.session(org_id=org_a) as session:
        row = (
            await session.execute(
                sql(
                    "SELECT password_hash, external_subject, is_active FROM app_user WHERE id = :id"
                ),
                {"id": created.user_id},
            )
        ).one()
        bindings = await session.scalar(
            sql("SELECT count(*) FROM role_binding WHERE user_id = :id"),
            {"id": created.user_id},
        )

    assert row.password_hash is None
    assert row.external_subject == "a-keycloak-subject"
    assert row.is_active is True
    assert bindings == 0, "provisioning must grant identity, never authority"

    # And it is findable by the two keys the service looks it up with.
    assert (await users.find_by_external_subject(org_a, "a-keycloak-subject")) == created
    assert (await users.find_by_email(org_a, "PROVISIONED@example.test")) == created, (
        "`email` is CITEXT: the match is case-insensitive in the database"
    )


async def test_record_login_stamps_last_login_at(
    users: SqlAppUserStore, db: Database, seeded: Seed
) -> None:
    org_a, user_a = seeded.org_a, seeded.user_a
    await users.record_login(org_a, user_a, NOW)

    async with db.session(org_id=org_a) as session:
        stamped = await session.scalar(
            sql("SELECT last_login_at FROM app_user WHERE id = :id"), {"id": user_a}
        )
    assert stamped == NOW


async def _row(db: Database, org_id: OrgId, session_id: SessionId) -> Row[Any]:
    """Read a `session` row's revocation columns, org-scoped like everything else."""
    async with db.session(org_id=org_id) as session:
        return (
            await session.execute(
                sql("SELECT revoked_at, revoked_reason FROM session WHERE id = :id"),
                {"id": session_id},
            )
        ).one()
