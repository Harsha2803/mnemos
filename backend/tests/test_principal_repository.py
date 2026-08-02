"""A0 — the guard's authority read, against a real Postgres.

`test_route_guard.py` proves the *policy* over an in-memory repository and says
so. This file exists because the claim the whole design rests on — **"changing a
role in the database changes the very next request"** — is a claim about the
database, and a fake would only prove the fake. The token is minted once and
never re-issued; everything that changes between the two calls changes in
Postgres.

It also keeps the thing every M3 test has to keep honest: the read runs as
`mnemos_app` (NOSUPERUSER, NOBYPASSRLS) with `app.current_org` bound by
`Database.session()`, so row-level security from migrations `0004`-`0006` is
underneath every predicate here. A join written against the wrong tenant is
caught by the policy and not merely by review.

Session-scoped container, shared with `test_tenant_isolation.py` and
`test_session_store.py`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.entrypoints.api.main import create_app
from mnemos.features.identity.adapters.principals import SqlPrincipalRepository
from mnemos.features.identity.application.principals import PrincipalResolver
from mnemos.features.identity.domain import OrgId, RoleId, SessionId, TagId, UserId
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

ORG_A_SLUG = "guard-org-a"
ORG_B_SLUG = "guard-org-b"

ANALYST_GRANTS = ["memory:read", "knowledge:read"]
ADMIN_GRANTS = ["*:*"]


class Seed(NamedTuple):
    """What the fixture wrote. Named for the reason `test_session_store.py`
    gives: `seeded[3]` in six tests is how a test ends up asserting about the
    wrong tenant without anybody noticing."""

    org_a: OrgId
    user_a: UserId
    session_a: SessionId
    analyst_role: RoleId
    admin_role: RoleId
    finance_tag: TagId
    public_tag: TagId
    org_b: OrgId
    user_b: UserId
    session_b: SessionId


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    """Two orgs. One user each, one live session each, and — in org A — two
    roles and two tags nothing is bound to yet.

    Seeded as the *owner*, for the reason `test_tenant_isolation.py` gives: it is
    the only role that can put another tenant's row in the table, which is what
    gives the unprivileged role something it must not see.
    """
    ids = Seed(
        org_a=OrgId(uuid7()),
        user_a=UserId(uuid7()),
        session_a=SessionId(uuid7()),
        analyst_role=RoleId(uuid7()),
        admin_role=RoleId(uuid7()),
        finance_tag=TagId(uuid7()),
        public_tag=TagId(uuid7()),
        org_b=OrgId(uuid7()),
        user_b=UserId(uuid7()),
        session_b=SessionId(uuid7()),
    )
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        for org_id, slug, user_id, session_id, email, name in (
            (ids.org_a, ORG_A_SLUG, ids.user_a, ids.session_a, "ada@guard.test", "Ada Analyst"),
            (ids.org_b, ORG_B_SLUG, ids.user_b, ids.session_b, "bob@guard.test", "Bob Other"),
        ):
            await conn.execute(
                "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)", org_id, slug, slug
            )
            await conn.execute(
                "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
                user_id,
                org_id,
                email,
                name,
            )
            await conn.execute(
                "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
                "VALUES ($1, $2, $3, $4, $5)",
                session_id,
                org_id,
                user_id,
                f"hash-for-{slug}",
                NOW + timedelta(days=14),
            )

        for role_id, role_slug, grants in (
            (ids.analyst_role, "analyst", ANALYST_GRANTS),
            (ids.admin_role, "admin", ADMIN_GRANTS),
        ):
            await conn.execute(
                "INSERT INTO role (id, org_id, slug, name, permissions, is_system) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, true)",
                role_id,
                ids.org_a,
                role_slug,
                role_slug,
                json.dumps(grants),
            )
        for tag_id, tag_slug in ((ids.finance_tag, "finance"), (ids.public_tag, "public")):
            await conn.execute(
                "INSERT INTO tag (id, org_id, slug, name) VALUES ($1, $2, $3, $4)",
                tag_id,
                ids.org_a,
                tag_slug,
                tag_slug,
            )

        yield ids
        await conn.execute("DELETE FROM org WHERE id = ANY($1::uuid[])", [ids.org_a, ids.org_b])
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
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def codec(clock: FrozenClock) -> PlatformTokenCodec:
    return PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER),
        clock=clock,
        ids=Uuid7Generator(),
    )


@pytest.fixture
def repository(db: Database) -> SqlPrincipalRepository:
    return SqlPrincipalRepository(db)


@pytest.fixture
def client(
    repository: SqlPrincipalRepository, codec: PlatformTokenCodec, clock: FrozenClock
) -> Iterator[TestClient]:
    """The real app and the real router, over the **real** repository.

    Only the `Database` underneath is redirected at the test container. That is
    the smallest substitution that leaves the guard, the SQL, the row-level
    security and the error boundary all genuinely under test.
    """
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(codec=codec, repository=repository, clock=clock)
        yield test_client


async def bind_role(postgres: Postgres, org_id: OrgId, user_id: UserId, role_id: RoleId) -> None:
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO role_binding (id, org_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
            uuid7(),
            org_id,
            user_id,
            role_id,
        )
    finally:
        await conn.close()


async def unbind_role(postgres: Postgres, user_id: UserId, role_id: RoleId) -> None:
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "DELETE FROM role_binding WHERE user_id = $1 AND role_id = $2", user_id, role_id
        )
    finally:
        await conn.close()


def bearer(codec: PlatformTokenCodec, seed: Seed) -> dict[str, str]:
    token, _ = codec.mint(subject=seed.user_a, org_id=seed.org_a, session_id=seed.session_a)
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------- the acceptance test


async def test_the_guard_hydrates_roles_from_the_repository_not_the_token(
    client: TestClient, codec: PlatformTokenCodec, postgres: Postgres, seeded: Seed
) -> None:
    """Mint one token, change the roles in the database, watch the next request
    change with them.

    **The token is minted exactly once and reused verbatim.** That is what makes
    this a test of hydration rather than of re-issuance: if any of the three
    answers below came out of the credential, all three would be identical.

    A grant *removed* is checked as well as a grant added, because those are two
    different bugs. An additive-only implementation — a cache that unions
    whatever it has seen — passes the first half and is precisely the thing that
    keeps a demoted user's authority alive.
    """
    headers = bearer(codec, seeded)

    # 1. No binding at all: authenticated, and authorized to do nothing.
    first = client.get("/api/v1/auth/me", headers=headers)
    assert first.status_code == 200
    assert first.json()["permissions"] == []
    assert first.json()["email"] == "ada@guard.test"
    assert first.json()["org_slug"] == ORG_A_SLUG

    # 2. Promoted in the database. Same token, next request.
    await bind_role(postgres, seeded.org_a, seeded.user_a, seeded.analyst_role)
    promoted = client.get("/api/v1/auth/me", headers=headers)
    assert promoted.json()["permissions"] == sorted(ANALYST_GRANTS)

    # 3. Demoted again. The half an additive cache would get wrong.
    await unbind_role(postgres, seeded.user_a, seeded.analyst_role)
    demoted = client.get("/api/v1/auth/me", headers=headers)
    assert demoted.json()["permissions"] == []


async def test_grants_from_two_bound_roles_are_unioned(
    client: TestClient, codec: PlatformTokenCodec, postgres: Postgres, seeded: Seed
) -> None:
    """`flatten_grants` over rows the database actually returned, rather than
    over a list a test wrote by hand."""
    await bind_role(postgres, seeded.org_a, seeded.user_a, seeded.analyst_role)
    await bind_role(postgres, seeded.org_a, seeded.user_a, seeded.admin_role)

    body = client.get("/api/v1/auth/me", headers=bearer(codec, seeded)).json()

    assert body["permissions"] == sorted([*ANALYST_GRANTS, *ADMIN_GRANTS])


async def test_tags_are_hydrated_from_user_tag_rows(
    client: TestClient, codec: PlatformTokenCodec, postgres: Postgres, seeded: Seed
) -> None:
    """Tags are the document-authorization axis (constraint C4) and they travel
    on the principal, so the guard has to load them for the retrieval scan to be
    able to push them into a `WHERE`."""
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        for tag_id in (seeded.finance_tag, seeded.public_tag):
            await conn.execute(
                "INSERT INTO user_tag (id, org_id, user_id, tag_id) VALUES ($1, $2, $3, $4)",
                uuid7(),
                seeded.org_a,
                seeded.user_a,
                tag_id,
            )
    finally:
        await conn.close()

    body = client.get("/api/v1/auth/me", headers=bearer(codec, seeded)).json()

    assert body["tags"] == ["finance", "public"]


# ------------------------------------------------------------------ tenant safety


async def test_a_token_naming_the_wrong_org_hydrates_nothing_and_is_denied(
    client: TestClient, codec: PlatformTokenCodec, postgres: Postgres, seeded: Seed
) -> None:
    """A signature we would happily verify, over a user that belongs to another
    tenant.

    Nothing about this token is forged: it is minted by our own codec with our
    own secret. What makes it useless is that the repository is scoped to the org
    the token names, so org B's user is simply not there to be found — and the
    read that would have found it runs as `mnemos_app`, where the policy is the
    second layer under the explicit predicate.
    """
    await bind_role(postgres, seeded.org_a, seeded.user_a, seeded.admin_role)
    token, _ = codec.mint(
        subject=seeded.user_a,  # org A's user...
        org_id=seeded.org_b,  # ...named under org B
        session_id=seeded.session_a,
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_a_role_belonging_to_another_org_is_never_joined_in(
    repository: SqlPrincipalRepository, postgres: Postgres, seeded: Seed
) -> None:
    """The join is written with `Role.org_id == org_id` as well as the binding's,
    and this is the test that would catch its removal.

    Row-level security would catch it too, which is the point of asserting it
    here: the two layers are meant to be independent, and a test that only
    proved one of them was in force would not notice the other going missing.
    """
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        foreign_role = RoleId(uuid7())
        await conn.execute(
            "INSERT INTO role (id, org_id, slug, name, permissions) "
            "VALUES ($1, $2, 'admin', 'admin', $3::jsonb)",
            foreign_role,
            seeded.org_b,
            json.dumps(["*:*"]),
        )
        await conn.execute(
            "INSERT INTO role_binding (id, org_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
            uuid7(),
            seeded.org_b,
            seeded.user_b,
            foreign_role,
        )
    finally:
        await conn.close()

    authority = await repository.load_authority(seeded.org_a, seeded.user_a)

    assert authority is not None
    assert authority.permissions == ()


# ----------------------------------------------------------------- session liveness


async def test_a_revoked_session_row_makes_the_access_token_dead(
    client: TestClient, codec: PlatformTokenCodec, postgres: Postgres, seeded: Seed
) -> None:
    """Sign-out, from the guard's side.

    `token:revoke` writes `revoked_at` on the whole family; this is the read that
    makes that write mean something before the access token's own `exp`.
    """
    headers = bearer(codec, seeded)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "UPDATE session SET revoked_at = $2, revoked_reason = 'signed_out' WHERE id = $1",
            seeded.session_a,
            NOW,
        )
    finally:
        await conn.close()

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


async def test_a_rotated_session_stays_live_until_its_own_expiry(
    repository: SqlPrincipalRepository, postgres: Postgres, seeded: Seed
) -> None:
    """Rotation retires a *refresh* token; it does not end the session.

    Treating a rotated row as dead would sign the user out on every refresh —
    which is the opposite of what refresh is for, and is the kind of bug that
    only appears fifteen minutes into a session.
    """
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        successor = SessionId(uuid7())
        await conn.execute(
            "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
            "VALUES ($1, $2, $3, 'successor-hash', $4)",
            successor,
            seeded.org_a,
            seeded.user_a,
            NOW + timedelta(days=14),
        )
        await conn.execute(
            "UPDATE session SET rotated_to = $2 WHERE id = $1", seeded.session_a, successor
        )
    finally:
        await conn.close()

    assert await repository.session_is_live(seeded.org_a, seeded.session_a, NOW) is True


async def test_an_expired_session_row_is_not_live(
    repository: SqlPrincipalRepository, seeded: Seed
) -> None:
    """The refresh window is fourteen days and it slides (§4 item 25); once it
    has genuinely lapsed, an access token minted inside it must not outlive it."""
    assert await repository.session_is_live(seeded.org_a, seeded.session_a, NOW) is True
    assert (
        await repository.session_is_live(seeded.org_a, seeded.session_a, NOW + timedelta(days=15))
        is False
    )


async def test_a_session_id_from_another_org_is_not_live(
    repository: SqlPrincipalRepository, seeded: Seed
) -> None:
    """The liveness read is org-scoped like every other. A session id is a UUIDv7
    and unguessable, but "unguessable" is not an authorization control."""
    assert await repository.session_is_live(seeded.org_a, seeded.session_b, NOW) is False


async def test_an_unknown_user_has_no_authority_rather_than_an_error(
    repository: SqlPrincipalRepository, seeded: Seed
) -> None:
    """`None`, not an exception. The caller turns it into the one denial; a
    repository that raised would make "no such user" a different code path from
    "wrong signature", which is how timing and status codes start to differ."""
    assert await repository.load_authority(seeded.org_a, UserId(uuid7())) is None
