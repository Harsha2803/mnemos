"""M3.4 — the auth endpoints, asserted **on the wire**.

This file exists because of the M3.2a lesson recorded in TRACKER §3: *a control
tested one layer below where it takes effect is not tested.* Every provider test
passed both before and after the error boundary was leaking `details`, because
they all assert on the raised exception and none of them looked at the response.

So everything here goes through the real `create_app()`, the real router, the
real error handler and a real HTTP client. What is asserted is what a caller can
observe: the status, the body, the `Set-Cookie` attributes, the CORS headers, and
the OpenAPI document the frontend client is generated from.

Hermetic. `Database` and `Cache` construct lazily, so the lifespan runs with no
Postgres and no Redis; the token service on `app.state` is the **real**
`TokenService` over the in-memory fakes from `test_refresh_rotation.py`. Faking
the service itself would leave the routes untested, which is the whole point.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mnemos.core.clock import FrozenClock
from mnemos.core.ids import Uuid7Generator
from mnemos.entrypoints.api.main import create_app
from mnemos.features.identity.application.tokens import TokenService
from mnemos.features.identity.domain import AccessTokenClaims, RefreshCredential
from mnemos.features.identity.providers import AUTHENTICATION_FAILED

from .test_refresh_rotation import (
    ACME,
    NOW,
    FakeSessions,
    FakeUsers,
    build_service,
    oidc_subject,
)

TOKEN_PATH = "/api/v1/auth/token"
REVOKE_PATH = "/api/v1/auth/token:revoke"
COOKIE = "mnemos_refresh"
FRONTEND_ORIGIN = "http://localhost:3000"


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def service(clock: FrozenClock) -> TokenService:
    return build_service(clock, FakeSessions(Uuid7Generator()), FakeUsers(), ACME)


@pytest.fixture
def client(service: TokenService) -> Iterator[TestClient]:
    """The real app, with the real routes, over a real `TokenService`.

    Only the two *stores* underneath it are fakes. The lifespan builds a
    Postgres-backed service and this replaces it after startup, which is the
    smallest substitution that keeps the routes, the models, the cookie code and
    the error boundary all genuinely under test.
    """
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.token_service = service
        yield test_client


async def _sign_in(service: TokenService) -> str:
    """Open a session the way the OIDC callback does, and return the credential."""
    pair = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    return pair.refresh_token


def _claims(access_token: str) -> AccessTokenClaims:
    import jwt

    return AccessTokenClaims.from_claims(
        jwt.decode(access_token, options={"verify_signature": False})
    )


# ------------------------------------------------------------------ the control


async def test_a_valid_refresh_token_yields_a_new_pair(
    client: TestClient, service: TokenService
) -> None:
    """The control. Every rejection below is one mutation away from this."""
    refresh_token = await _sign_in(service)

    response = client.post(
        TOKEN_PATH, json={"grant_type": "refresh_token", "refresh_token": refresh_token}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    assert body["org_slug"] == "acme"
    assert _claims(body["access_token"]).org_id == ACME.org_id


async def test_the_refresh_token_is_never_in_the_response_body(
    client: TestClient, service: TokenService
) -> None:
    """The assertion behind `TokenResponse` having no `refresh_token` field.

    A body is the part of a response most likely to reach a log, a proxy cache or
    a pasted bug report, and a browser client handed a refresh token in JSON will
    put it somewhere a script can read. The cookie is the only channel.
    """
    refresh_token = await _sign_in(service)
    response = client.post(
        TOKEN_PATH, json={"grant_type": "refresh_token", "refresh_token": refresh_token}
    )

    assert "refresh_token" not in response.json()
    # Not under any other key either, however the body is later restructured.
    issued = client.cookies.get(COOKIE)
    assert issued is not None
    assert issued not in response.text
    assert refresh_token not in response.text


async def test_the_browser_can_refresh_with_the_cookie_alone(
    client: TestClient, service: TokenService
) -> None:
    """The browser case: an `httpOnly` cookie cannot be read back into a body, so
    the endpoint has to accept it from the cookie or the frontend cannot work."""
    refresh_token = await _sign_in(service)
    client.cookies.set(COOKIE, refresh_token, path="/api/v1/auth")

    first = client.post(TOKEN_PATH, json={"grant_type": "refresh_token"})
    assert first.status_code == 200

    # And the client is now holding the *rotated* token, so it can go again.
    second = client.post(TOKEN_PATH, json={"grant_type": "refresh_token"})
    assert second.status_code == 200
    assert second.json()["access_token"] != first.json()["access_token"]


# ---------------------------------------------------------------- the cookie


async def test_the_refresh_cookie_is_httponly_lax_and_path_scoped(
    client: TestClient, service: TokenService
) -> None:
    """Four attributes, each load-bearing, so each is asserted rather than assumed.

    `HttpOnly` keeps it out of reach of any XSS. `SameSite=Lax` is what makes a
    cookie-borne credential safe on a POST endpoint — Lax withholds it from
    cross-site POSTs, so a forged form on another origin sends nothing. `Path`
    keeps it off every non-auth API call. `Max-Age` matches the refresh TTL, so a
    browser drops it when it can no longer be useful.
    """
    refresh_token = await _sign_in(service)
    response = client.post(
        TOKEN_PATH, json={"grant_type": "refresh_token", "refresh_token": refresh_token}
    )

    header = response.headers["set-cookie"]
    assert header.startswith(f"{COOKIE}=")
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Path=/api/v1/auth" in header
    assert f"Max-Age={60 * 60 * 24 * 14}" in header
    # Not `Secure` under the local default, because the dev stack is plain http
    # and a `Secure` cookie there is silently dropped. `refresh_cookie_is_secure`
    # flips it everywhere else; see `core/config.py`.
    assert "Secure" not in header


async def test_revoke_clears_the_cookie_and_kills_the_session(
    client: TestClient, service: TokenService
) -> None:
    refresh_token = await _sign_in(service)
    client.cookies.set(COOKIE, refresh_token, path="/api/v1/auth")

    revoked = client.post(REVOKE_PATH, json={})

    assert revoked.status_code == 204
    assert revoked.content == b""
    header = revoked.headers["set-cookie"]
    assert f"{COOKIE}=" in header
    assert "Max-Age=0" in header or "expires=Thu, 01 Jan 1970" in header.lower()
    assert "Path=/api/v1/auth" in header

    # And the credential really is dead, not merely forgotten by the browser.
    assert (
        client.post(
            TOKEN_PATH, json={"grant_type": "refresh_token", "refresh_token": refresh_token}
        ).status_code
        == 401
    )


# ------------------------------------------------- the boundary (the M3.2a test)


@pytest.mark.parametrize(
    "presented",
    [
        "garbage",
        "acme.not-a-real-secret",
        "nosuchorg.secret",
        "",
        ".",
        "acme." + "x" * 4096,
    ],
)
async def test_the_token_endpoint_leaks_nothing_in_its_error_body(
    client: TestClient, presented: str
) -> None:
    """**The M3.2a assertion, at the layer where it takes effect.**

    `denied()` puts a constant message in `message` and the diagnostic truth in
    `details`, and the error handler renders only the first. Every one of these
    inputs produces a *different* internal reason — malformed credential, no such
    org, no session holds this hash — and the caller must not be able to tell them
    apart, or an unauthenticated caller can enumerate tenants for free.

    Asserted on the response bytes rather than on the raised exception, because
    that is exactly the gap that let the boundary leak `details` through all of
    M3.2 with every provider test green.
    """
    response = client.post(
        TOKEN_PATH, json={"grant_type": "refresh_token", "refresh_token": presented}
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthenticated", "message": AUTHENTICATION_FAILED}
    }
    for leak in ("reason", "org", "slug", "session", "hash", "nosuchorg", "acme", "detail"):
        assert leak not in response.text.lower(), f"{leak!r} leaked into the error body"


async def test_every_token_failure_is_byte_identical(
    client: TestClient, service: TokenService
) -> None:
    """Unknown org, unknown token, revoked family and a rotated replay must be one
    answer. Any difference between them is a distinction an attacker can measure.
    """
    first = await _sign_in(service)
    second = (
        client.post(
            TOKEN_PATH, json={"grant_type": "refresh_token", "refresh_token": first}
        ).status_code,
    )
    assert second == (200,)

    bodies = {
        client.post(
            TOKEN_PATH, json={"grant_type": "refresh_token", "refresh_token": presented}
        ).text
        for presented in (
            "nosuchorg.secret",  # unknown tenant
            "acme.never-issued",  # unknown token
            first,  # a rotated token: kills the family
            first,  # and again, now against a revoked family
        )
    }
    assert len(bodies) == 1, f"the four denials differ on the wire: {bodies}"


async def test_a_missing_credential_is_the_same_denial_not_a_500(
    client: TestClient,
) -> None:
    """No body field and no cookie. A caller that simply forgot must get the
    ordinary denial rather than a stack trace."""
    response = client.post(TOKEN_PATH, json={"grant_type": "refresh_token"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == AUTHENTICATION_FAILED


async def test_an_unsupported_grant_type_is_rejected_by_the_schema(
    client: TestClient,
) -> None:
    """`Literal["refresh_token"]` means the password and api_key grants 422 here
    rather than falling into a branch that does not exist yet. A grant that
    silently no-ops is worse than one that is refused."""
    for grant in ("password", "client_credentials", "api_key", ""):
        response = client.post(TOKEN_PATH, json={"grant_type": grant, "refresh_token": "a.b"})
        assert response.status_code == 422


@pytest.mark.parametrize("presented", ["garbage", "acme.never-issued", "", "nosuchorg.x"])
async def test_revoke_answers_204_to_anything(client: TestClient, presented: str) -> None:
    """RFC 7009 §2.2. Answering 401 for an unknown token and 204 for a known one
    is a free oracle for testing stolen credentials, from a caller whose only
    authentication *is* the token."""
    response = client.post(REVOKE_PATH, json={"refresh_token": presented})
    assert response.status_code == 204
    assert response.content == b""


async def test_revoke_answers_204_with_no_credential_at_all(client: TestClient) -> None:
    assert client.post(REVOKE_PATH, json={}).status_code == 204


# ----------------------------------------------------------------------- CORS


def test_the_frontend_origin_may_send_and_receive_credentials(client: TestClient) -> None:
    """The cookie is useless to the frontend unless CORS allows credentials.

    A browser refuses a credentialed response whose `Access-Control-Allow-Origin`
    is `*`, so this also pins that the middleware echoes the *specific* origin —
    which is only possible because `cors_origins` is an explicit list. Widening it
    to a wildcard "to make CORS work" would break exactly this.
    """
    preflight = client.options(
        TOKEN_PATH,
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert preflight.headers["access-control-allow-credentials"] == "true"

    actual = client.post(
        TOKEN_PATH,
        json={"grant_type": "refresh_token", "refresh_token": "acme.nope"},
        headers={"Origin": FRONTEND_ORIGIN},
    )
    assert actual.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert actual.headers["access-control-allow-credentials"] == "true"


def test_an_unlisted_origin_gets_no_credentialed_response(client: TestClient) -> None:
    response = client.options(
        TOKEN_PATH,
        headers={
            "Origin": "http://evil.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "http://evil.test"


# -------------------------------------------------------------------- OpenAPI


def test_the_token_endpoints_appear_correctly_in_openapi(client: TestClient) -> None:
    """The frontend client is generated from this document, so a route that is
    wrong here is a compile error in a codebase nobody has written yet — or worse,
    a runtime shape mismatch in front of a user."""
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    assert "/api/v1/auth/token" in paths
    assert "/api/v1/auth/token:revoke" in paths
    assert "/api/v1/auth/oidc/callback" in paths

    ok = paths["/api/v1/auth/token"]["post"]["responses"]["200"]
    schema_ref = ok["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/TokenResponse")

    token_response = spec["components"]["schemas"]["TokenResponse"]
    assert set(token_response["properties"]) == {
        "access_token",
        "token_type",
        "expires_in",
        "org_slug",
    }, "the refresh token must not be part of the generated client's response type"

    # 204 means the generated client types sign-out as returning nothing.
    assert "204" in paths["/api/v1/auth/token:revoke"]["post"]["responses"]


def test_the_callback_is_typed_as_a_redirect_and_carries_no_token_schema(
    client: TestClient,
) -> None:
    """M3.3's `SubjectResponse` is gone from the document as well as from the
    code — a stale schema is what a generated client would still believe.

    A0 replaced M3.4's `TokenResponse` body here with a 303. The only caller this
    endpoint has is a browser arriving by top-level navigation from Keycloak, and
    a JSON body is, to a browser, a page of machine-readable text where an
    application should be. The generated frontend client must therefore *not*
    believe there is a token to read out of this response.
    """
    spec = client.get("/openapi.json").json()

    assert "SubjectResponse" not in spec["components"]["schemas"]
    callback = spec["paths"]["/api/v1/auth/oidc/callback"]["get"]["responses"]
    assert "303" in callback
    assert "200" not in callback
    assert "TokenResponse" not in str(callback)


# -------------------------------------------------------- the callback, end to end


async def test_the_callback_sets_the_cookie_and_returns_the_browser_to_the_app(
    client: TestClient, service: TokenService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3.3 ended at a verified subject; this is the change that makes a login
    survive a reload.

    The OIDC flow itself is pinned in `test_oidc_login_flow.py` against a fake
    IdP; what is under test here is only the last step — that the callback turns
    a completed login into a refresh cookie and a redirect the browser can
    follow back to the application.

    **No credential in the URL.** The access token is not there and must never
    be: a query string ends up in browser history, in the `Referer` of the next
    request, and in every proxy log along the way. The page at the redirect
    target exchanges the cookie for one, which is asserted at the end.
    """
    from mnemos.features.identity.application.oidc_login import CompletedLogin

    async def complete(*, state: str, code: str) -> CompletedLogin:
        assert (state, code) == ("a-stored-state", "an-authorization-code")
        return CompletedLogin(subject=oidc_subject(), org_slug="acme", provider_slug="keycloak")

    monkeypatch.setattr(client.app.state.oidc_login, "complete", complete)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/auth/oidc/callback",
        params={"state": "a-stored-state", "code": "an-authorization-code"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/signin/complete"
    assert "access_token" not in response.headers["location"]
    assert response.text == ""

    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    assert "SameSite=lax" in header

    # The cookie holds a usable credential for this tenant, and exchanging it is
    # how the page at that URL gets an access token naming the session it opened.
    credential = RefreshCredential.parse(client.cookies[COOKIE])
    assert credential.org_slug == "acme"

    exchanged = client.post(TOKEN_PATH, json={"grant_type": "refresh_token"})
    assert exchanged.status_code == 200
    assert _claims(exchanged.json()["access_token"]).session_id is not None


async def test_the_callback_returns_a_failed_login_to_the_signin_screen(
    client: TestClient,
) -> None:
    """The IdP's error strings are diagnostic and can name internal
    configuration, so they never reach the caller — not in a body, and not in
    the redirect either.

    What the browser gets is one constant flag with nothing to branch on, which
    is the same guarantee the JSON denial made, expressed in the medium the
    caller is actually using.
    """
    response = client.get(
        "/api/v1/auth/oidc/callback",
        params={"state": "s", "error": "invalid_client: mnemos-web is misconfigured"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/signin?error=auth_failed"
    assert "misconfigured" not in response.text
    assert "misconfigured" not in response.headers["location"]
    assert COOKIE not in response.headers.get("set-cookie", "")


async def test_every_login_failure_produces_the_same_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The M3.2a lesson, applied to the medium a browser reads.

    `test_every_token_failure_is_byte_identical` asserts it for the JSON
    endpoints. These two routes answer with a `Location` header instead, so the
    header is what has to be identical — an `error=no_such_org` next to an
    `error=access_denied` would be exactly the tenant-enumeration oracle the
    constant message exists to close, moved into a URL where it is *more*
    visible, not less.
    """
    from mnemos.features.identity.providers import denied

    async def refuse(**_: object) -> None:
        raise denied("no org with slug 'nosuchorg'")

    monkeypatch.setattr(client.app.state.oidc_login, "begin", refuse)  # type: ignore[attr-defined]
    monkeypatch.setattr(client.app.state.oidc_login, "complete", refuse)  # type: ignore[attr-defined]

    locations = {
        client.get(
            "/api/v1/auth/oidc/authorize", params={"org": "nosuchorg"}, follow_redirects=False
        ).headers["location"],
        client.get(
            "/api/v1/auth/oidc/authorize",
            params={"org": "acme", "provider": "internal"},
            follow_redirects=False,
        ).headers["location"],
        client.get(
            "/api/v1/auth/oidc/callback",
            params={"state": "replayed"},
            follow_redirects=False,
        ).headers["location"],
        client.get(
            "/api/v1/auth/oidc/callback",
            params={"state": "s", "error": "access_denied"},
            follow_redirects=False,
        ).headers["location"],
    }

    assert locations == {"http://localhost:3000/signin?error=auth_failed"}


async def test_the_authorize_route_still_redirects_a_good_request_to_the_idp(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the two tests above: a guard that redirected *everything*
    to the sign-in screen would satisfy both of them and would be a login nobody
    can complete."""
    from mnemos.features.identity.application.oidc_login import AuthorizationRedirect

    async def begin(**_: object) -> AuthorizationRedirect:
        return AuthorizationRedirect(
            url="http://localhost:8080/realms/mnemos/protocol/openid-connect/auth?state=x",
            state="x",
        )

    monkeypatch.setattr(client.app.state.oidc_login, "begin", begin)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/auth/oidc/authorize", params={"org": "acme"}, follow_redirects=False
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith("http://localhost:8080/realms/mnemos/")
