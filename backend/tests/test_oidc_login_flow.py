"""M3.3 — the OIDC authorization-code + PKCE round trip.

What M3.2 could not test: the flow *obtains* a token rather than being handed one.
The assertions here are mostly about the **requests the flow makes**, because that
is where the controls live — the browser must be sent to the public issuer, the
code must be exchanged over the internal one, the verifier must go to the token
endpoint and never the challenge, and a `state` must be single-use.

Hermetic against an `httpx.MockTransport` Keycloak. There is one live-stack test
at the bottom, skipped when the stack is down, and it is the one that discharges
the "nothing has proved this against the realm as shipped" gap.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from mnemos.core.errors import AuthenticationError
from mnemos.core.security import PasswordHasher
from mnemos.features.identity.application.oidc_login import (
    LoginState,
    OidcLoginFlow,
)
from mnemos.features.identity.domain import OrgId, ProviderId
from mnemos.features.identity.providers import (
    AUTHENTICATION_FAILED,
    HttpJwksCache,
    HttpOidcMetadata,
    OrgRecord,
    ProviderFactory,
    ProviderRecord,
)
from tests.oidc_support import (
    CLIENT_ID,
    ISSUER_INTERNAL,
    ISSUER_PUBLIC,
    SUBJECT,
    FakeIdp,
    generate_key,
    mint,
)
from tests.test_identity_providers import FakeOrgDirectory, FakeUserDirectory

ORG_ID = OrgId(uuid4())
PROVIDER_ID = ProviderId(uuid4())
REDIRECT_URI = "http://localhost:8000/api/v1/auth/oidc/callback"


class FakeStateStore:
    """In-memory `LoginStateStore` with the single-use property preserved.

    Single-use is the behaviour under test, so the fake must have it — the Redis
    adapter gets it from `GETDEL`; this gets it from `pop`. A fake that let a
    state be read twice would make the replay tests vacuous.
    """

    def __init__(self) -> None:
        self.values: dict[str, LoginState] = {}
        self.ttls: list[int] = []

    async def put(self, state: str, value: LoginState, *, ttl_s: int) -> None:
        self.values[state] = value
        self.ttls.append(ttl_s)

    async def take(self, state: str) -> LoginState | None:
        return self.values.pop(state, None)


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return generate_key()


@pytest.fixture
def idp(key: rsa.RSAPrivateKey) -> FakeIdp:
    return FakeIdp(key)


@pytest.fixture
def states() -> FakeStateStore:
    return FakeStateStore()


def _provider_record(**overrides: Any) -> ProviderRecord:
    base: dict[str, Any] = {
        "provider_id": PROVIDER_ID,
        "org_id": ORG_ID,
        "slug": "keycloak",
        "kind": "oidc",
        "is_enabled": True,
        "issuer_public": ISSUER_PUBLIC,
        "issuer_internal": ISSUER_INTERNAL,
        "client_id": CLIENT_ID,
    }
    return ProviderRecord(**{**base, **overrides})


def build_flow(
    idp: FakeIdp, states: FakeStateStore, *, provider: ProviderRecord | None = None
) -> OidcLoginFlow:
    client = httpx.AsyncClient(transport=idp.transport)
    metadata = HttpOidcMetadata(client=client, ttl_s=900)
    factory = ProviderFactory(
        orgs=FakeOrgDirectory(
            OrgRecord(org_id=ORG_ID, slug="acme", is_active=True),
            [provider or _provider_record()],
        ),
        users=FakeUserDirectory(),
        hasher=PasswordHasher(),
        jwks=HttpJwksCache(client=client, ttl_s=900, metadata=metadata),
    )
    return OidcLoginFlow(
        factory=factory,
        metadata=metadata,
        states=states,
        client=client,
        state_ttl_s=600,
    )


# --------------------------------------------------------------- authorize


async def test_authorize_redirects_to_the_public_issuer_with_pkce_and_state(
    idp: FakeIdp, states: FakeStateStore
) -> None:
    """The single most important assertion in M3.3.

    `keycloak:8080` does not resolve in a browser. Sending the user there is the
    classic containerised-OIDC failure, and it fails as a blank page rather than
    as an error anybody can read.
    """
    redirect = await build_flow(idp, states).begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )

    parsed = urlparse(redirect.url)
    query = parse_qs(parsed.query)

    assert redirect.url.startswith(ISSUER_PUBLIC), "the browser must go to the public issuer"
    assert "keycloak:8080" not in redirect.url
    assert parsed.path.endswith("/protocol/openid-connect/auth")

    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [redirect.state]
    assert "openid" in query["scope"][0], "no `openid` scope means no id_token to validate"

    # Discovery still runs over the internal issuer — that is split horizon, not
    # an inconsistency.
    assert any("keycloak:8080" in url for url in idp.requested_urls)


async def test_authorize_sends_the_challenge_and_keeps_the_verifier(
    idp: FakeIdp, states: FakeStateStore
) -> None:
    """PKCE is only worth anything if the verifier stays here. If the challenge
    were the verifier, an interceptor of the redirect could redeem the code."""
    redirect = await build_flow(idp, states).begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )
    challenge = parse_qs(urlparse(redirect.url).query)["code_challenge"][0]
    verifier = states.values[redirect.state].code_verifier

    assert challenge != verifier
    assert verifier not in redirect.url
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert challenge == expected
    assert "=" not in challenge, "S256 challenges are unpadded base64url"


async def test_authorize_state_and_verifier_are_unpredictable(
    idp: FakeIdp, states: FakeStateStore
) -> None:
    """Both are guessed by an attacker if they repeat."""
    flow = build_flow(idp, states)
    for _ in range(5):
        await flow.begin(org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI)

    assert len(states.values) == 5, "every login gets its own state"
    assert len({v.code_verifier for v in states.values.values()}) == 5
    # RFC 7636 requires 43-128 characters.
    for value in states.values.values():
        assert 43 <= len(value.code_verifier) <= 128
    assert states.ttls == [600] * 5, "state must expire; an immortal state is a standing credential"


async def test_authorize_denies_an_org_or_provider_that_is_not_oidc(
    idp: FakeIdp, states: FakeStateStore
) -> None:
    flow = build_flow(idp, states, provider=_provider_record(kind="internal", slug="internal"))
    with pytest.raises(AuthenticationError) as denial:
        await flow.begin(org_slug="acme", provider_slug="internal", redirect_uri=REDIRECT_URI)
    assert denial.value.message == AUTHENTICATION_FAILED

    with pytest.raises(AuthenticationError):
        await build_flow(idp, states).begin(
            org_slug="no-such-org", provider_slug="keycloak", redirect_uri=REDIRECT_URI
        )


# ---------------------------------------------------------------- callback


async def test_callback_exchanges_the_code_and_returns_a_verified_subject(
    idp: FakeIdp, states: FakeStateStore
) -> None:
    """The control. Every rejection below is one mutation away from this."""
    flow = build_flow(idp, states)
    redirect = await flow.begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )
    completed = await flow.complete(state=redirect.state, code="an-authorization-code")

    assert completed.org_slug == "acme"
    assert completed.subject.external_subject == SUBJECT
    assert completed.subject.email == "ada@example.test"
    assert completed.subject.org_id == ORG_ID
    # No local user is resolved: provisioning is the application layer's call.
    assert completed.subject.user_id is None


async def test_the_code_is_exchanged_over_the_internal_issuer_with_the_verifier(
    idp: FakeIdp, states: FakeStateStore
) -> None:
    """Server-to-server, so the internal host is correct here — the mirror image
    of the browser redirect."""
    flow = build_flow(idp, states)
    redirect = await flow.begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )
    verifier = states.values[redirect.state].code_verifier
    await flow.complete(state=redirect.state, code="an-authorization-code")

    assert len(idp.token_requests) == 1
    sent = idp.token_requests[0]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "an-authorization-code"
    assert sent["code_verifier"] == verifier
    assert sent["client_id"] == CLIENT_ID
    # Must match `authorize` byte-for-byte or the IdP rejects the exchange.
    assert sent["redirect_uri"] == REDIRECT_URI

    token_calls = [u for u in idp.requested_urls if u.endswith("/token")]
    assert token_calls
    assert all("keycloak:8080" in u for u in token_calls)


async def test_callback_rejects_an_unknown_state(idp: FakeIdp, states: FakeStateStore) -> None:
    with pytest.raises(AuthenticationError) as denial:
        await build_flow(idp, states).complete(state="never-issued", code="c")
    assert denial.value.message == AUTHENTICATION_FAILED
    assert not idp.token_requests, "an unverified state must not reach the token endpoint"


async def test_callback_rejects_a_replayed_state(idp: FakeIdp, states: FakeStateStore) -> None:
    """State is consumed on first use. A second callback with the same state is a
    replay, and replay is how a stolen code gets a second chance."""
    flow = build_flow(idp, states)
    redirect = await flow.begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )
    await flow.complete(state=redirect.state, code="an-authorization-code")

    with pytest.raises(AuthenticationError):
        await flow.complete(state=redirect.state, code="an-authorization-code")
    assert len(idp.token_requests) == 1, "the replay must not reach the token endpoint either"


async def test_callback_takes_the_org_from_stored_state_not_from_the_request(
    idp: FakeIdp, states: FakeStateStore
) -> None:
    """`complete()` has no org parameter at all, which is the point: a callback
    that named its own tenant could be pointed at a different org's provider."""
    flow = build_flow(idp, states)
    redirect = await flow.begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )
    states.values[redirect.state] = LoginState(
        org_slug="some-other-org",
        provider_slug="keycloak",
        code_verifier=states.values[redirect.state].code_verifier,
        redirect_uri=REDIRECT_URI,
    )
    # The org from state is the one resolved, and it does not exist here.
    with pytest.raises(AuthenticationError):
        await flow.complete(state=redirect.state, code="c")


@pytest.mark.parametrize(
    ("response", "why"),
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), "the IdP refused the code"),
        (httpx.Response(200, json={"access_token": "a"}), "no id_token in the response"),
        (httpx.Response(200, text="not json"), "a non-JSON body"),
        (httpx.Response(500, text="boom"), "the IdP is broken"),
    ],
)
async def test_callback_denies_when_the_token_exchange_does_not_yield_an_id_token(
    key: rsa.RSAPrivateKey, states: FakeStateStore, response: httpx.Response, why: str
) -> None:
    """No `id_token` means no identity contract. Falling back to the access token
    would authenticate against a token that never promised to name a user."""
    idp = FakeIdp(key, token_response=response)
    flow = build_flow(idp, states)
    redirect = await flow.begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )
    with pytest.raises(AuthenticationError) as denial:
        await flow.complete(state=redirect.state, code="c")
    assert denial.value.message == AUTHENTICATION_FAILED, why


async def test_a_token_fetched_by_us_is_still_validated(
    key: rsa.RSAPrivateKey, states: FakeStateStore
) -> None:
    """ "We fetched it over TLS from the IdP" proves the transport, not the
    contents. A token for another client in the same realm must still be refused.
    """
    forged = FakeIdp(
        key,
        token_response=httpx.Response(
            200,
            json={"id_token": mint(key, azp="some-other-client", audience="account")},
        ),
    )
    flow = build_flow(forged, states)
    redirect = await flow.begin(
        org_slug="acme", provider_slug="keycloak", redirect_uri=REDIRECT_URI
    )
    with pytest.raises(AuthenticationError):
        await flow.complete(state=redirect.state, code="c")


# ------------------------------------------------------- against live Keycloak

# From the host, `keycloak:8080` does not resolve — it is a compose-network name.
# So this test points both issuers at `localhost:8080`. The *two-issuer* logic is
# what the hermetic tests above cover; what only a live IdP can prove is that a
# token Keycloak actually mints, signed by a key fetched from its real JWKS, is
# accepted by this validator. That is the gap, and it is the one that would have
# hidden a wrong `aud`/`azp` or `iss` assumption.
LIVE_ISSUER = "http://localhost:8080/realms/mnemos"
LIVE_USER = "user@mnemos.local"
LIVE_PASSWORD = "user"


def _keycloak_is_up() -> bool:
    try:
        response = httpx.get(f"{LIVE_ISSUER}/.well-known/openid-configuration", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == httpx.codes.OK


live_keycloak = pytest.mark.skipif(
    not _keycloak_is_up(),
    reason="Keycloak is not running: `docker compose up -d keycloak`",
)


@live_keycloak
async def test_a_real_keycloak_token_is_accepted_by_the_validator() -> None:
    """End-to-end against the realm as shipped.

    Uses the direct-grant endpoint rather than driving a browser through the code
    flow: what is being proved is that a *genuine Keycloak-minted ID token*
    validates, and the code flow's own moving parts (PKCE, state, the redirect
    host) are pinned hermetically above. Driving a real browser here would add a
    Playwright dependency to prove something already proved.
    """
    from mnemos.features.identity.providers import OidcConfig, OidcProvider

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{LIVE_ISSUER}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": CLIENT_ID,
                "username": LIVE_USER,
                "password": LIVE_PASSWORD,
                # Without `openid` Keycloak returns no id_token at all.
                "scope": "openid",
            },
            timeout=10.0,
        )
        assert response.status_code == httpx.codes.OK, response.text
        id_token = response.json()["id_token"]

        provider = OidcProvider(
            provider_id=PROVIDER_ID,
            org_id=ORG_ID,
            config=OidcConfig.build(
                issuer_internal=LIVE_ISSUER, issuer_public=LIVE_ISSUER, client_id=CLIENT_ID
            ),
            jwks=HttpJwksCache(client=client, ttl_s=900),
        )
        subject = await provider.authenticate(token=id_token)

    assert subject.email == LIVE_USER
    assert subject.external_subject, "a real token names a Keycloak subject"
    assert subject.org_id == ORG_ID


@live_keycloak
async def test_the_realm_allows_the_api_callback_as_a_redirect_uri() -> None:
    """A redirect URI Keycloak does not know about fails at the *authorize* step
    with an error page, not at the callback — so it is worth checking directly
    rather than discovering it by hand in a browser.

    Keycloak answers an unregistered `redirect_uri` with 400 and its own error
    page; a registered one gets 302 to the login form (or 200 for the form
    itself). The distinction is what this asserts.
    """
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid",
        "state": "probe",
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256",
    }
    async with httpx.AsyncClient(follow_redirects=False) as client:
        allowed = await client.get(
            f"{LIVE_ISSUER}/protocol/openid-connect/auth", params=params, timeout=10.0
        )
        refused = await client.get(
            f"{LIVE_ISSUER}/protocol/openid-connect/auth",
            params={**params, "redirect_uri": "http://not-registered.test/callback"},
            timeout=10.0,
        )

    assert allowed.status_code != httpx.codes.BAD_REQUEST, (
        "the API callback is not in the realm's redirectUris; "
        "re-import with `docker compose up -d --force-recreate keycloak`"
    )
    assert refused.status_code == httpx.codes.BAD_REQUEST, (
        "Keycloak accepted an unregistered redirect_uri — the allow-list is not doing its job"
    )
