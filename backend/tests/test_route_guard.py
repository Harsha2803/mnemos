"""A0 — the fail-closed route guard, asserted on the wire.

The claim under test is not "the dependency works" but **"a route nobody
protected is protected"**, and that can only be asserted by adding a route that
declares nothing and watching it refuse. `_probe/unguarded` below exists for
exactly that: it has no dependencies, no decorator, no mention of
authentication, and it must answer 401.

Hermetic, in the shape `test_auth_endpoints.py` established: the real
`create_app()`, the real router, the real error handler and a real HTTP client,
with only the *repository* faked. Faking the resolver would leave the thing
under test — the wiring between a global dependency, a token codec and a
database read — untested, which is the M3.2a lesson (TRACKER §3): a control
asserted one layer below where it takes effect is not asserted.

`tests/test_principal_repository.py` runs the same guard against a real Postgres,
because "the repository read reflects a role change" is a property of the
database and a fake would only prove the fake.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.routing import Route

from mnemos.core.clock import FrozenClock
from mnemos.core.ids import Uuid7Generator
from mnemos.entrypoints.api.main import create_app
from mnemos.entrypoints.api.security import DOCUMENTATION_PATHS, public_route_paths
from mnemos.features.identity.application.principals import (
    PrincipalResolver,
    UserAuthority,
    flatten_grants,
)
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.providers import (
    AUTHENTICATION_FAILED,
    PlatformTokenCodec,
    PlatformTokenConfig,
)

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

ORG = OrgId(uuid4())
USER = UserId(uuid4())
SESSION = SessionId(uuid4())

UNGUARDED_PATH = "/_probe/unguarded"

DENIAL = {"error": {"code": "unauthenticated", "message": AUTHENTICATION_FAILED}}


class FakeRepository:
    """`PrincipalRepository` in memory. Mutable, because the point of the guard
    is that changing a row changes the *next* request."""

    def __init__(self) -> None:
        self.authority = UserAuthority(
            user_id=USER,
            org_id=ORG,
            org_slug="acme",
            email="ada@example.test",
            display_name="Ada Admin",
            is_active=True,
            permissions=("memory:read",),
            tags=("public",),
        )
        self.live_sessions: set[SessionId] = {SESSION}
        self.authority_reads = 0

    async def load_authority(self, org_id: OrgId, user_id: UserId) -> UserAuthority | None:
        self.authority_reads += 1
        if org_id != self.authority.org_id or user_id != self.authority.user_id:
            return None
        return self.authority

    async def session_is_live(self, org_id: OrgId, session_id: SessionId, at: datetime) -> bool:
        return session_id in self.live_sessions


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
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def client(
    codec: PlatformTokenCodec, repository: FakeRepository, clock: FrozenClock
) -> Iterator[TestClient]:
    app = create_app()

    async def unguarded() -> JSONResponse:
        """A route with **no** guard, no decorator, and no idea it is protected.

        Registered exactly the way a feature router's endpoint is registered.
        Nothing about it opts in to authentication; if the request reaches this
        body without a credential, the application is fail-open.
        """
        return JSONResponse({"reached": True})

    app.add_api_route(UNGUARDED_PATH, unguarded, methods=["GET"])

    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(codec=codec, repository=repository, clock=clock)
        yield test_client


def bearer(codec: PlatformTokenCodec) -> dict[str, str]:
    token, _ = codec.mint(subject=USER, org_id=ORG, session_id=SESSION)
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------------- the two acceptance tests


def test_unauthenticated_request_is_denied_by_default(client: TestClient) -> None:
    """The criterion, on a route that declares no guard at all.

    Written before the guard existed and watched to fail: without
    `dependencies=[Depends(enforce_authentication)]` on the application, this
    answers 200 with `{"reached": true}`.

    The body is asserted too, not just the status. A 401 that explained *why* —
    "no such session", "token expired" — would be a working guard and a new
    oracle, and the identity layer spent M3.2 and M3.2a making sure there is only
    one answer.
    """
    response = client.get(UNGUARDED_PATH)

    assert response.status_code == 401
    assert response.json() == DENIAL


def test_a_route_in_the_public_allowlist_is_reachable_without_a_token(
    client: TestClient,
) -> None:
    """The control, and it is not optional.

    A guard that refuses everything passes the test above. Without this, the
    whole file would be satisfied by an application that answers 401 to its own
    liveness probe — which is a working guard and a service no orchestrator will
    keep running.
    """
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/").status_code == 200


def test_a_genuine_access_token_reaches_the_route(
    client: TestClient, codec: PlatformTokenCodec
) -> None:
    """The other control. Every denial below is one mutation away from this."""
    response = client.get(UNGUARDED_PATH, headers=bearer(codec))

    assert response.status_code == 200
    assert response.json() == {"reached": True}


# --------------------------------------------------------------- the allow-list


def test_the_public_allowlist_is_exact_paths_and_never_a_prefix() -> None:
    """The failure mode this list is shaped to avoid.

    `/api/v1/auth` as a *prefix* makes every future route beneath it public —
    `/auth/users`, `/auth/keys`, `/auth/orgs` — and the person adding one of
    those would have no reason to look at an allow-list they never touched.
    Membership in a set of literal strings cannot do that, and this test is what
    stops somebody "simplifying" it into a `startswith`.
    """
    paths = public_route_paths("/api/v1")

    assert "/api/v1/auth/token" in paths
    # The nearby paths a prefix match would have swallowed.
    assert "/api/v1/auth" not in paths
    assert "/api/v1/auth/me" not in paths
    assert "/api/v1/auth/token/steal" not in paths
    assert "/api/v1/auth/users" not in paths


def test_a_path_that_merely_resembles_a_public_one_is_denied(client: TestClient) -> None:
    """Every near-miss falls the safe way.

    `/healthz` is public; `/healthzz` is not a route at all, and `/api/v1/auth/me`
    starts with a public path and must still be refused. A guard whose edge cases
    fall the *unsafe* way is worse than no guard, because it is trusted.
    """
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/healthzz").status_code == 404


def test_the_authenticated_route_is_absent_from_the_allowlist_and_the_public_ones_are_in_it(
    client: TestClient,
) -> None:
    """The enumeration and the application agree, checked both ways.

    Reading the app's own route table rather than a hand-written list, so a route
    added later shows up here instead of being remembered about.
    """
    paths = client.app.state.public_route_paths  # type: ignore[attr-defined]

    for public in ("/", "/healthz", "/readyz", "/api/v1/auth/token", "/api/v1/auth/token:revoke"):
        assert public in paths
    assert "/api/v1/auth/me" not in paths
    assert UNGUARDED_PATH not in paths


def test_every_route_the_guard_cannot_reach_is_named_in_the_allowlist(
    client: TestClient,
) -> None:
    """The docs UI and the schema are plain Starlette routes, so they carry no
    dependencies and the guard never runs for them however it is installed.

    That makes them public by construction rather than by decision — which is
    fine, and is exactly the kind of thing that stops being fine when a future
    FastAPI adds a fifth one. Naming them in the allow-list turns "public
    because of how the framework works" into "public because we said so", and
    this test fails the day the framework adds one we did not say.
    """
    paths = client.app.state.public_route_paths  # type: ignore[attr-defined]
    unguardable = {
        route.path
        for route in client.app.routes  # type: ignore[attr-defined]
        if type(route) is Route
    }

    assert unguardable == DOCUMENTATION_PATHS
    assert unguardable <= paths


# ------------------------------------------------------- what the guard refuses


@pytest.mark.parametrize(
    ("header", "why"),
    [
        ({}, "no header at all"),
        ({"Authorization": ""}, "an empty header"),
        ({"Authorization": "Bearer"}, "a scheme with no token"),
        ({"Authorization": "Bearer   "}, "whitespace where a token should be"),
        ({"Authorization": "Basic YWRtaW46YWRtaW4="}, "the wrong scheme"),
        ({"Authorization": "not-a-scheme token"}, "a scheme nobody defined"),
        ({"Authorization": "Bearer not.a.jwt"}, "a token that is not a JWT"),
    ],
)
def test_every_malformed_credential_gets_the_same_answer(
    client: TestClient, header: dict[str, str], why: str
) -> None:
    """One body for seven different mistakes.

    `HTTPBearer` from FastAPI would have answered 403 with `{"detail": "Not
    authenticated"}` for some of these and 401 for others — a second error shape
    competing with the API's own, and a distinction a caller could enumerate
    against. The guard raises the same `AuthenticationError` the identity layer
    raises, so one handler renders all of it.
    """
    response = client.get(UNGUARDED_PATH, headers=header)

    assert response.status_code == 401, why
    assert response.json() == DENIAL, why


def test_the_scheme_is_matched_case_insensitively(
    client: TestClient, codec: PlatformTokenCodec
) -> None:
    """RFC 7235 §2.1 says the scheme is case-insensitive, and clients take it at
    its word. Rejecting `bearer` would be a bug that only some HTTP libraries
    reveal."""
    token = bearer(codec)["Authorization"].split(" ", 1)[1]

    assert (
        client.get(UNGUARDED_PATH, headers={"Authorization": f"bearer {token}"}).status_code == 200
    )
    assert (
        client.get(UNGUARDED_PATH, headers={"Authorization": f"BEARER {token}"}).status_code == 200
    )


def test_an_expired_access_token_is_refused_at_the_boundary_second(
    client: TestClient, codec: PlatformTokenCodec, clock: FrozenClock
) -> None:
    """Zero leeway, asserted where it actually matters.

    The codec's own test pins the arithmetic; this pins that the *guard* consults
    it, which is a different claim — a guard that decoded claims itself would
    pass every codec test in the suite.
    """
    headers = bearer(codec)

    clock.advance(seconds=899)
    assert client.get(UNGUARDED_PATH, headers=headers).status_code == 200

    clock.advance(seconds=1)
    assert client.get(UNGUARDED_PATH, headers=headers).status_code == 401


def test_a_token_signed_with_a_different_secret_is_refused(client: TestClient) -> None:
    """The forgery the whole scheme exists to stop, at the boundary rather than
    at the codec."""
    forged = PlatformTokenCodec(
        config=PlatformTokenConfig(
            secret="another-thirty-two-byte-or-longer-secret", issuer=ISSUER
        ),
        clock=FrozenClock(NOW),
        ids=Uuid7Generator(),
    )

    response = client.get(UNGUARDED_PATH, headers=bearer(forged))

    assert response.status_code == 401
    assert response.json() == DENIAL


def test_a_token_for_a_user_who_no_longer_exists_is_refused(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    """A valid signature over a deleted user is still a valid signature. The row
    is what decides."""
    repository.authority = replace(repository.authority, user_id=UserId(uuid4()))

    assert client.get(UNGUARDED_PATH, headers=bearer(codec)).status_code == 401


def test_a_deactivated_user_is_refused_on_the_next_request(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    """Deactivation takes effect immediately, not in fifteen minutes.

    This is the property that a `roles` claim in the token would have destroyed,
    stated for the coarsest possible grant.
    """
    headers = bearer(codec)
    assert client.get(UNGUARDED_PATH, headers=headers).status_code == 200

    repository.authority = replace(repository.authority, is_active=False)

    assert client.get(UNGUARDED_PATH, headers=headers).status_code == 401


def test_a_revoked_session_kills_the_access_token_it_minted(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    """Why `sid` is in the token at all.

    Signing out revokes the refresh family; without this check the access token
    would keep working for the rest of its lifetime, and "sign out" would mean
    "sign out in up to fifteen minutes". `AccessTokenClaims` carries the session
    id precisely so the question can be asked without the token carrying the
    answer.
    """
    headers = bearer(codec)
    assert client.get(UNGUARDED_PATH, headers=headers).status_code == 200

    repository.live_sessions.clear()

    assert client.get(UNGUARDED_PATH, headers=headers).status_code == 401


def test_the_guard_reads_authority_on_every_request_and_not_once_per_token(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    """Caching the hydration per token would quietly restore the property the
    token was built to avoid, so the absence of a cache is pinned rather than
    assumed. If a cache is ever added it must be keyed on something a revocation
    invalidates, and this test is where that conversation starts."""
    headers = bearer(codec)

    for _ in range(3):
        client.get(UNGUARDED_PATH, headers=headers)

    assert repository.authority_reads == 3


# ---------------------------------------------------------------- what /auth/me says


def test_auth_me_reports_the_repositorys_answer_and_not_the_tokens(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    """The hydration, observable from outside the process.

    The token carries no `roles` claim at all — `test_access_token_carries_no
    _roles_or_permissions` pins that — so every grant in this body came from the
    repository on this request. Changing the repository between two calls with
    **the same token** is the whole demonstration.
    """
    headers = bearer(codec)

    before = client.get("/api/v1/auth/me", headers=headers)
    assert before.status_code == 200
    assert before.json()["permissions"] == ["memory:read"]
    assert before.json()["org_slug"] == "acme"
    assert before.json()["email"] == "ada@example.test"

    repository.authority = replace(
        repository.authority, permissions=("memory:read", "knowledge:write")
    )

    after = client.get("/api/v1/auth/me", headers=headers)
    assert after.json()["permissions"] == ["knowledge:write", "memory:read"]


def test_auth_me_is_not_reachable_without_a_token(client: TestClient) -> None:
    """It is behind the guard because it is absent from the allow-list, not
    because it decorated itself. That is the arrangement being tested."""
    assert client.get("/api/v1/auth/me").status_code == 401


def test_auth_me_appears_in_openapi_so_the_generated_client_can_call_it(
    client: TestClient,
) -> None:
    """The frontend's client is generated from this document, and the sidebar
    footer is the first thing that needs a name to put in it."""
    spec = client.get("/openapi.json").json()

    assert "/api/v1/auth/me" in spec["paths"]
    schema = spec["components"]["schemas"]["MeResponse"]
    assert {"email", "org_slug", "display_name", "permissions", "tags"} <= set(schema["properties"])


# --------------------------------------------------------------- grant flattening


def test_grants_from_several_bound_roles_are_unioned_and_deduplicated() -> None:
    """Bindings are additive, and a permission held twice is held once.

    In the application layer rather than in the SQL because it is a rule about
    the model: a second repository would have to union them the same way, and a
    `DISTINCT` in one adapter is not a rule anybody else can find.
    """
    assert flatten_grants([["memory:read", "chat:write"], ["memory:read", "*:*"]]) == (
        "memory:read",
        "chat:write",
        "*:*",
    )


def test_a_malformed_grant_in_one_role_does_not_deny_the_whole_principal(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    """`PermissionSet.parse` is deliberately tolerant (M3.1), and this is where
    that decision is felt: one bad string in a role's JSONB must not be able to
    lock a user out of the entire application."""
    repository.authority = replace(
        repository.authority, permissions=("memory:read", "not a permission", "")
    )

    response = client.get("/api/v1/auth/me", headers=bearer(codec))

    assert response.status_code == 200
    assert response.json()["permissions"] == ["memory:read"]


def test_the_session_liveness_check_is_asked_about_the_injected_clocks_moment(
    client: TestClient,
) -> None:
    """The moment reaching the repository is the injected clock's, not the wall
    clock's.

    Nothing else in the suite would notice a resolver that reached for
    `datetime.now()` — the expiry test above would still pass, because the token
    would be expired by the real clock too. So the assertion has to be that the
    *frozen* value is what arrives, and a clock a quarter-century in the past is
    unmistakable about it.
    """
    long_ago = datetime(2001, 1, 1, tzinfo=UTC)
    clock = FrozenClock(long_ago)
    codec = PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER),
        clock=clock,
        ids=Uuid7Generator(),
    )
    seen: list[datetime] = []

    class RecordingRepository(FakeRepository):
        async def session_is_live(self, org_id: OrgId, session_id: SessionId, at: datetime) -> bool:
            seen.append(at)
            return True

    client.app.state.principals = PrincipalResolver(  # type: ignore[attr-defined]
        codec=codec, repository=RecordingRepository(), clock=clock
    )

    assert client.get(UNGUARDED_PATH, headers=bearer(codec)).status_code == 200
    assert seen == [long_ago]
    assert datetime.now(UTC) - seen[0] > timedelta(days=365)
