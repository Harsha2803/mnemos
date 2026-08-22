"""`C3` deliverable 5 — the audit log viewer, on the wire.

Real `create_app()`, real router, real `SqlAuditRepository`/`SqlPrincipalRepository`
against real Postgres — the permission gate is a claim about the live
`role.permissions` grants and RLS, and a fake would only prove the fake.
Uses the actual production `SYSTEM_ROLES` (`admin`'s `*:*`, `user`'s bounded
grants) rather than inventing test-only permission sets, so this stays true
to what `mnemosctl bootstrap` actually seeds.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

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
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.domain.roles import SYSTEM_ROLES
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.features.observability.adapters.repository import SqlAuditRepository
from mnemos.features.observability.application.service import AuditService
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

ORG_A_SLUG = "audit-org-a"
ORG_B_SLUG = "audit-org-b"


class Seed:
    def __init__(
        self,
        org_a: OrgId,
        admin_user: UserId,
        admin_session: SessionId,
        plain_user: UserId,
        plain_session: SessionId,
        org_b: OrgId,
        org_b_user: UserId,
        org_b_session: SessionId,
    ) -> None:
        self.org_a = org_a
        self.admin_user = admin_user
        self.admin_session = admin_session
        self.plain_user = plain_user
        self.plain_session = plain_session
        self.org_b = org_b
        self.org_b_user = org_b_user
        self.org_b_session = org_b_session


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    ids = Seed(
        org_a=OrgId(uuid7()),
        admin_user=UserId(uuid7()),
        admin_session=SessionId(uuid7()),
        plain_user=UserId(uuid7()),
        plain_session=SessionId(uuid7()),
        org_b=OrgId(uuid7()),
        org_b_user=UserId(uuid7()),
        org_b_session=SessionId(uuid7()),
    )
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            ids.org_a,
            ORG_A_SLUG,
            ORG_A_SLUG,
        )
        await conn.execute(
            "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
            ids.org_b,
            ORG_B_SLUG,
            ORG_B_SLUG,
        )
        role_ids = {}
        for role in SYSTEM_ROLES:
            role_id = uuid7()
            role_ids[role.slug] = role_id
            await conn.execute(
                "INSERT INTO role (id, org_id, slug, name, permissions, is_system) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, true)",
                role_id,
                ids.org_a,
                role.slug,
                role.name,
                json.dumps(role.grants),
            )
        for user_id, session_id, email, role_slug, org_id in (
            (ids.admin_user, ids.admin_session, "admin@audit.test", "admin", ids.org_a),
            (ids.plain_user, ids.plain_session, "user@audit.test", "user", ids.org_a),
        ):
            await conn.execute(
                "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
                user_id,
                org_id,
                email,
                email,
            )
            await conn.execute(
                "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
                "VALUES ($1, $2, $3, $4, $5)",
                session_id,
                org_id,
                user_id,
                f"hash-for-{email}",
                NOW + timedelta(days=14),
            )
            await conn.execute(
                "INSERT INTO role_binding (id, org_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
                uuid7(),
                org_id,
                user_id,
                role_ids[role_slug],
            )
        await conn.execute(
            "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
            ids.org_b_user,
            ids.org_b,
            "other-org@audit.test",
            "other-org@audit.test",
        )
        await conn.execute(
            "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
            "VALUES ($1, $2, $3, $4, $5)",
            ids.org_b_session,
            ids.org_b,
            ids.org_b_user,
            "hash-for-other-org",
            NOW + timedelta(days=14),
        )
        # A row for org A, seeded directly — this deliverable's write path is
        # already covered end to end elsewhere (tools/memory/knowledge/nl2sql
        # tests); this file is about the *viewer* and its permission gate.
        await conn.execute(
            "INSERT INTO audit_log (id, org_id, actor_id, actor_kind, action, resource_kind, "
            "resource_id, outcome) VALUES ($1, $2, $3, 'user', 'auth.sign_in', 'session', NULL, 'allow')",
            uuid7(),
            ids.org_a,
            ids.admin_user,
        )
        yield ids
        await conn.execute("DELETE FROM org WHERE id = ANY($1::uuid[])", [ids.org_a, ids.org_b])
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db(postgres: Postgres) -> AsyncIterator[Database]:
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
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER), clock=clock, ids=Uuid7Generator()
    )


def bearer(
    codec: PlatformTokenCodec, *, user: UserId, org: OrgId, session: SessionId
) -> dict[str, str]:
    token, _ = codec.mint(subject=user, org_id=org, session_id=session)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(codec: PlatformTokenCodec, clock: FrozenClock, db: Database) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(
            codec=codec, repository=SqlPrincipalRepository(db), clock=clock
        )
        app.state.audit_service = AuditService(repository=SqlAuditRepository(db, Uuid7Generator()))
        yield test_client


def test_an_admin_sees_the_seeded_event(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = bearer(codec, user=seeded.admin_user, org=seeded.org_a, session=seeded.admin_session)

    response = client.get("/api/v1/audit/events", headers=headers)

    assert response.status_code == 200
    [event] = response.json()["events"]
    assert event["action"] == "auth.sign_in"
    assert event["outcome"] == "allow"
    assert event["actor_id"] == str(seeded.admin_user)


def test_a_plain_user_is_refused_with_a_real_403(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """`audit:read` is granted only by `admin`'s `*:*` wildcard — `user`'s
    grants (`chat:*`, `context:read`, `document:read`, `memory:read`) do not
    include it, by design (`roles.py`)."""
    headers = bearer(codec, user=seeded.plain_user, org=seeded.org_a, session=seeded.plain_session)

    response = client.get("/api/v1/audit/events", headers=headers)

    assert response.status_code == 403
    assert "administrators" in response.json()["error"]["message"]


def test_an_admin_from_another_org_never_sees_org_as_events(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """Org B's caller has no role binding at all here — RLS and the missing
    grant both refuse it, but the 403 must fire before RLS ever gets a
    chance to just return an empty list that looks the same as "no events"."""
    headers = bearer(codec, user=seeded.org_b_user, org=seeded.org_b, session=seeded.org_b_session)

    response = client.get("/api/v1/audit/events", headers=headers)

    assert response.status_code == 403


def test_filtering_by_action_and_outcome(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = bearer(codec, user=seeded.admin_user, org=seeded.org_a, session=seeded.admin_session)

    matching = client.get(
        "/api/v1/audit/events",
        params={"action": "auth.sign_in", "outcome": "allow"},
        headers=headers,
    )
    assert len(matching.json()["events"]) == 1

    no_match = client.get("/api/v1/audit/events", params={"outcome": "deny"}, headers=headers)
    assert no_match.json()["events"] == []
