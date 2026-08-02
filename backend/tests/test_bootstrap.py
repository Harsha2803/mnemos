"""M3.7 — `mnemosctl bootstrap`, against a real Postgres.

**Why a container and not a fake.** Everything this command is claimed to do is a
property of the database it writes to: that the org insert survives without a
tenant GUC, that the *other* nine inserts survive *with* one and would be rejected
without it, that the `SET LOCAL ROLE` reverts, and that a second run collides with
the unique indexes rather than duplicating rows. A fake store would prove that the
fake is idempotent. `test_identity_providers.py` argues the opposite way about
provider logic, and both arguments are the same rule applied honestly: use the
real thing where the real thing is the subject.

The two tests that matter most are the last two.
`test_bootstrap_admin_can_authenticate_through_the_internal_provider` is the end
of the loop — it proves the seeded rows are the *shape* M3.2 expects rather than
merely present, which is the failure a row-count assertion cannot see.
`test_bootstrap_does_not_leave_an_elevated_session_open` guards the one mistake in
this command that would be silent and catastrophic: a leaked `SET ROLE` disables
tenant isolation for every later query on that pooled connection, and nothing else
in the suite would notice.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from jwt import PyJWK
from sqlalchemy import text

from mnemos.core.config import Settings
from mnemos.core.errors import AuthenticationError, ValidationError
from mnemos.core.security import PasswordHasher
from mnemos.core.types import ProviderKind
from mnemos.features.identity.adapters.bootstrap_store import SqlBootstrapStore
from mnemos.features.identity.adapters.directory import SqlOrgDirectory, SqlUserDirectory
from mnemos.features.identity.application.bootstrap import (
    INTERNAL_PROVIDER_SLUG,
    OIDC_PROVIDER_SLUG,
    Bootstrap,
    BootstrapReport,
    BootstrapRequest,
    OidcSettings,
)
from mnemos.features.identity.domain import ADMIN_ROLE_SLUG, SYSTEM_ROLES, Permission, PermissionSet
from mnemos.features.identity.providers import (
    InternalProvider,
    OidcProvider,
    ProviderFactory,
)
from mnemos.platform.db import Database

from .conftest import Postgres

ORG_SLUG = "bootstrap-org"
ORG_NAME = "Bootstrap Org"
ADMIN_EMAIL = "admin@mnemos.local"
ADMIN_PASSWORD = "correct horse battery staple"
SECOND_PASSWORD = "an entirely different passphrase"

# The realm as shipped in `deploy/keycloak/mnemos-realm.json`, and the split the
# compose file actually uses: the browser is sent to `localhost`, the API talks to
# the service name. Seeding the same URL into both columns is the bug this pair of
# constants exists to make visible in the assertions.
ISSUER_PUBLIC = "http://localhost:8080/realms/mnemos"
ISSUER_INTERNAL = "http://keycloak:8080/realms/mnemos"
CLIENT_ID = "mnemos-web"


def _request(*, password: str = ADMIN_PASSWORD, org_name: str = ORG_NAME) -> BootstrapRequest:
    return BootstrapRequest(
        org_slug=ORG_SLUG,
        org_name=org_name,
        admin_email=ADMIN_EMAIL,
        admin_display_name="Ada Admin",
        admin_password=password,
        oidc=OidcSettings(
            issuer_public=ISSUER_PUBLIC,
            issuer_internal=ISSUER_INTERNAL,
            client_id=CLIENT_ID,
        ),
        default_provider_slug=OIDC_PROVIDER_SLUG,
    )


@pytest.fixture(scope="session")
def hasher() -> PasswordHasher:
    """Production argon2 parameters, not cheapened ones.

    The point of the authentication test below is that a hash written by the
    bootstrap verifies under the hasher the running system uses. Weakening the
    parameters here would test a hasher that does not ship.
    """
    return PasswordHasher()


@pytest_asyncio.fixture
async def db(postgres: Postgres) -> AsyncIterator[Database]:
    """A `Database` connected as `mnemos_app` — the unprivileged application role.

    Deliberately not the owner. Connecting as the owner would make every
    assertion below vacuous: RLS does not apply to a superuser, so a leaked
    elevation would be indistinguishable from no elevation at all.
    """
    database = Database(Settings(database_url=postgres.app_url, env="test"))
    try:
        yield database
    finally:
        await database.dispose()


@pytest_asyncio.fixture
async def clean_org(postgres: Postgres) -> AsyncIterator[None]:
    """Remove the bootstrapped org before and after each test.

    As the owner, because deleting an org is exactly the cross-tenant write the
    application role must not be able to perform. `ON DELETE CASCADE` on `org_id`
    takes the roles, providers, user and binding with it.
    """

    async def drop() -> None:
        conn = await asyncpg.connect(postgres.owner_dsn)
        try:
            await conn.execute("DELETE FROM org WHERE slug = $1", ORG_SLUG)
        finally:
            await conn.close()

    await drop()
    yield
    await drop()


async def _bootstrap(
    db: Database,
    hasher: PasswordHasher,
    *,
    password: str = ADMIN_PASSWORD,
    org_name: str = ORG_NAME,
) -> BootstrapReport:
    request = _request(password=password, org_name=org_name)
    return await Bootstrap(store=SqlBootstrapStore(db), hasher=hasher).execute(request)


async def _counts(postgres: Postgres, org_id: uuid.UUID) -> dict[str, int]:
    """Row counts for the org, read as the owner so RLS cannot mask a duplicate."""
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        return {
            table: await conn.fetchval(f"SELECT count(*) FROM {table} WHERE org_id = $1", org_id)
            for table in ("role", "identity_provider", "app_user", "role_binding")
        }
    finally:
        await conn.close()


# ----------------------------------------------------------------- the rows


async def test_bootstrap_creates_the_first_org_and_admin(
    postgres: Postgres, db: Database, hasher: PasswordHasher, clean_org: None
) -> None:
    """One run turns an empty database into one somebody can sign in to."""
    report = await _bootstrap(db, hasher)

    assert report.org_created
    assert report.admin_created
    assert report.role_binding_created
    assert report.default_provider_set
    assert report.org_slug == ORG_SLUG
    assert report.admin_email == ADMIN_EMAIL

    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        org = await conn.fetchrow("SELECT * FROM org WHERE slug = $1", ORG_SLUG)
        assert org is not None
        assert org["is_active"] is True

        user = await conn.fetchrow(
            "SELECT * FROM app_user WHERE org_id = $1 AND email = $2", org["id"], ADMIN_EMAIL
        )
        assert user is not None
        assert user["is_active"] is True
        # argon2id specifically, not "some hash". A bcrypt or SHA prefix here
        # would still let the login test below pass while quietly abandoning the
        # memory-hard property `core/security.py` is built around.
        assert user["password_hash"].startswith("$argon2id$")
        assert ADMIN_PASSWORD not in user["password_hash"]

        roles = await conn.fetch(
            "SELECT slug, is_system FROM role WHERE org_id = $1 ORDER BY slug", org["id"]
        )
        assert [row["slug"] for row in roles] == sorted(r.slug for r in SYSTEM_ROLES)
        assert all(row["is_system"] for row in roles)

        providers = await conn.fetch(
            "SELECT * FROM identity_provider WHERE org_id = $1 ORDER BY slug", org["id"]
        )
        by_slug = {row["slug"]: row for row in providers}
        assert set(by_slug) == {INTERNAL_PROVIDER_SLUG, OIDC_PROVIDER_SLUG}
        assert by_slug[INTERNAL_PROVIDER_SLUG]["kind"] == ProviderKind.INTERNAL.value
        assert by_slug[OIDC_PROVIDER_SLUG]["kind"] == ProviderKind.OIDC.value

        # Split horizon: two different URLs, or the API and the browser cannot
        # both reach the IdP (ADAPTATION §8, M3.3).
        assert by_slug[OIDC_PROVIDER_SLUG]["issuer_public"] == ISSUER_PUBLIC
        assert by_slug[OIDC_PROVIDER_SLUG]["issuer_internal"] == ISSUER_INTERNAL
        assert by_slug[OIDC_PROVIDER_SLUG]["client_id"] == CLIENT_ID

        binding = await conn.fetchrow(
            """
            SELECT r.slug FROM role_binding b
              JOIN role r ON r.id = b.role_id
             WHERE b.user_id = $1
            """,
            user["id"],
        )
        assert binding is not None
        assert binding["slug"] == ADMIN_ROLE_SLUG
    finally:
        await conn.close()


async def test_bootstrap_is_idempotent(
    postgres: Postgres, db: Database, hasher: PasswordHasher, clean_org: None
) -> None:
    """A second run creates nothing, changes nothing, and does not raise.

    Run with a *different* password and a *different* org name on purpose. Equal
    row counts alone would also be satisfied by an implementation that updated
    every row in place — which is the behaviour this command explicitly refuses,
    because it would reset the administrator's password on every re-run.
    """
    first = await _bootstrap(db, hasher)
    before = await _counts(postgres, first.org_id)

    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        original_hash = await conn.fetchval(
            "SELECT password_hash FROM app_user WHERE org_id = $1", first.org_id
        )
    finally:
        await conn.close()

    second = await _bootstrap(db, hasher, password=SECOND_PASSWORD, org_name="Renamed Org")

    assert second.org_id == first.org_id
    # The report describes the database, not the request: a run that asked for a
    # rename and did not perform one must not print the name it asked for.
    assert second.org_name == ORG_NAME
    assert not second.created_anything
    assert not second.org_created
    assert not second.admin_created
    assert not second.role_binding_created
    assert not second.default_provider_set
    assert all(not row.created for row in second.roles)
    assert all(not row.created for row in second.providers)

    assert await _counts(postgres, first.org_id) == before
    assert before == {
        "role": len(SYSTEM_ROLES),
        "identity_provider": 2,
        "app_user": 1,
        "role_binding": 1,
    }

    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        assert (
            await conn.fetchval(
                "SELECT password_hash FROM app_user WHERE org_id = $1", first.org_id
            )
            == original_hash
        ), "a re-run rewrote the admin's password hash"
        assert (
            await conn.fetchval("SELECT name FROM org WHERE id = $1", first.org_id) == ORG_NAME
        ), "a re-run renamed the org"
    finally:
        await conn.close()


# -------------------------------------------------------- the point of it all


async def test_bootstrap_admin_can_authenticate_through_the_internal_provider(
    db: Database, hasher: PasswordHasher, clean_org: None
) -> None:
    """The seeded rows are the shape M3.2 expects, not merely present.

    This is the whole justification for the task: before it, nothing in the
    provider seam could be exercised against a real database by hand. It goes
    through `ProviderFactory` rather than constructing an `InternalProvider`
    directly, because the factory is what reads `identity_provider` — building the
    strategy by hand would skip the row this command exists to write.
    """
    report = await _bootstrap(db, hasher)

    factory = ProviderFactory(
        orgs=SqlOrgDirectory(db),
        users=SqlUserDirectory(db),
        hasher=hasher,
        jwks=_UnusedJwks(),
    )
    provider = await factory.for_org(ORG_SLUG, INTERNAL_PROVIDER_SLUG)
    assert isinstance(provider, InternalProvider)

    subject = await provider.authenticate(email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
    assert subject.user_id == report.admin_user_id
    assert subject.org_id == report.org_id
    assert subject.email == ADMIN_EMAIL
    assert subject.provider_kind is ProviderKind.INTERNAL

    # The control. A provider that accepted anything would pass the assertions
    # above and prove nothing about the stored hash.
    with pytest.raises(AuthenticationError):
        await provider.authenticate(email=ADMIN_EMAIL, password=SECOND_PASSWORD)


async def test_bootstrap_seeds_a_default_provider_the_factory_resolves_to_oidc(
    db: Database, hasher: PasswordHasher, clean_org: None
) -> None:
    """`?org=<slug>` with no provider named must reach Keycloak, not deny.

    Two enabled providers and no `org.settings.default_provider` is the factory's
    "ambiguous default" denial — so seeding both rows without the setting would
    leave the org *less* usable than seeding neither. This asserts the setting is
    the thing that resolves it.
    """
    await _bootstrap(db, hasher)

    factory = ProviderFactory(
        orgs=SqlOrgDirectory(db), users=SqlUserDirectory(db), hasher=hasher, jwks=_UnusedJwks()
    )
    provider = await factory.for_org(ORG_SLUG)
    assert isinstance(provider, OidcProvider), "the org default must be the OIDC provider"

    # Read back through the same port the factory used, so the assertion is about
    # `org.settings` and not about a value this test happened to remember.
    org = await SqlOrgDirectory(db).find_org(ORG_SLUG)
    assert org is not None
    assert org.default_provider_slug == OIDC_PROVIDER_SLUG


# ------------------------------------------------------------- the elevation


async def test_bootstrap_does_not_leave_an_elevated_session_open(
    db: Database, hasher: PasswordHasher, clean_org: None
) -> None:
    """`SET LOCAL ROLE` reverts, so isolation is back on for the next query.

    A leak here is silent: every subsequent query on that pooled connection would
    run with `BYPASSRLS` and return other tenants' rows, and no other test in the
    suite touches the same `Database` instance afterwards to notice.

    The first block is the **control**. Without it, the assertions after the
    bootstrap would also pass against an implementation that never elevated at
    all, and the test would be pinning nothing.
    """
    async with db.elevated_session() as session:
        elevated_role = await session.scalar(text("SELECT current_user"))
    assert elevated_role == "mnemos_admin", "the elevated session did not actually elevate"

    await _bootstrap(db, hasher)

    async with db.session() as session:
        # Same pool, and with one connection ever checked out at a time it is the
        # same connection the elevated transaction used.
        assert await session.scalar(text("SELECT current_user")) == "mnemos_app"
        assert (
            await session.scalar(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
            is False
        )
        # The real assertion: unscoped, so every row returned would be a row the
        # policy failed to hide. Bootstrap just wrote three roles under this org.
        assert await session.scalar(text("SELECT count(*) FROM role")) == 0
        assert await session.scalar(text("SELECT count(*) FROM app_user")) == 0


async def test_bootstrap_writes_the_org_scoped_rows_under_the_tenant_guc(
    db: Database, hasher: PasswordHasher, clean_org: None
) -> None:
    """Only the org row is written elevated; the rest are checked by the policy.

    Proved from the other side: with the GUC bound to the bootstrapped org, an
    unprivileged session sees exactly the rows that run wrote. If those inserts
    had been made from the elevated transaction they would still be here — so the
    assertion that carries the weight is the previous test's, and this one pins
    that narrowing to an org-scoped session did not lose any rows.
    """
    report = await _bootstrap(db, hasher)

    async with db.session(org_id=report.org_id) as session:
        assert await session.scalar(text("SELECT count(*) FROM role")) == len(SYSTEM_ROLES)
        assert await session.scalar(text("SELECT count(*) FROM identity_provider")) == 2
        assert await session.scalar(text("SELECT count(*) FROM app_user")) == 1
        assert await session.scalar(text("SELECT count(*) FROM role_binding")) == 1


# ------------------------------------------------------------ hermetic checks


def test_system_roles_are_expressed_in_permission_vocabulary() -> None:
    """The seeded grants parse back into exactly the permissions they name.

    `role.permissions` is a JSONB list of strings and `PermissionSet.parse` is
    deliberately tolerant of garbage — it drops what it cannot read rather than
    failing a login. That tolerance means a typo in `SYSTEM_ROLES` would ship a
    role silently short one grant, so the round trip is asserted rather than
    assumed.
    """
    for role in SYSTEM_ROLES:
        assert PermissionSet.parse(role.grants) == role.permissions
        assert len(role.grants) == len(role.permissions)

    admin = next(role for role in SYSTEM_ROLES if role.slug == ADMIN_ROLE_SLUG)
    assert admin.permissions.allows(Permission.require("memory", "write"))
    assert admin.permissions.allows(Permission.require("a-capability-that-does-not-exist", "yet"))

    user = next(role for role in SYSTEM_ROLES if role.slug == "user")
    assert user.permissions.allows(Permission.require("chat", "write"))
    assert not user.permissions.allows(Permission.require("role", "manage"))
    assert not user.permissions.allows(Permission.require("tool", "invoke"))


def test_a_short_admin_password_is_refused_before_anything_is_written() -> None:
    """The floor is enforced in the request, not in the CLI.

    In the request because a future admin API that provisions a second org would
    otherwise inherit none of these rules simply by not knowing they exist. Also
    checks that the rejected value is not carried in `details` — `ValidationError`
    is the one error whose details cross the API boundary.
    """
    with pytest.raises(ValidationError) as caught:
        _request(password="short")
    assert "short" not in str(caught.value.details)


class _UnusedJwks:
    """A `JwksSource` these tests never reach.

    `ProviderFactory` requires one to construct an `OidcProvider`; nothing here
    validates a token, and a fixture that quietly returned a key would hide the
    day something started needing one.
    """

    async def key_for(self, issuer: str, kid: str | None) -> PyJWK:
        msg = "these tests must not reach the IdP"
        raise AssertionError(msg)
