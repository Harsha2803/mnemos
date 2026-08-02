"""M3.2 — the authentication strategy seam: internal, OIDC, and the factory.

Hermetic: no Docker, no network, no Keycloak. That is a deliberate contrast with
`test_tenant_isolation.py`, and the distinction is worth stating because it is the
one that decides when a fake is legitimate. Tenant isolation is a property *of
Postgres*, so a fake would only prove the fake isolates. What these tests pin is a
property of **this code** — that an argon2 hash matches, that a signature is
checked against a key we chose, that a wrong issuer or audience or an expired
`exp` is refused, that an unknown provider denies rather than raises. A real IdP
would make those slower to run and no more true, so the SQL and the HTTP arrive
through the ports and the JWKS cache is exercised against `httpx.MockTransport`.

The rejection tests are only meaningful next to the acceptance test: a validator
that rejects everything passes every "rejects a forged token" case. So
`test_oidc_provider_accepts_a_genuine_token` runs first and is what the rest are
deviations from.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from mnemos.core.errors import AuthenticationError
from mnemos.core.security import PasswordHasher, digest_token, tokens_equal
from mnemos.core.types import ProviderKind
from mnemos.features.identity.domain import OrgId, ProviderId, UserId
from mnemos.features.identity.providers import (
    AUTHENTICATION_FAILED,
    AuthenticatedSubject,
    CredentialAuthProvider,
    HttpJwksCache,
    HttpOidcMetadata,
    InternalProvider,
    OidcConfig,
    OidcProvider,
    OrgRecord,
    ProviderFactory,
    ProviderRecord,
    TokenAuthProvider,
    UserCredentialRecord,
    public_authorization_endpoint,
)

ORG_ID = OrgId(uuid4())
PROVIDER_ID = ProviderId(uuid4())
USER_ID = UserId(uuid4())

PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "correct horse battery stapl3"

ISSUER_INTERNAL = "http://keycloak:8080/realms/mnemos"
ISSUER_PUBLIC = "http://localhost:8080/realms/mnemos"
CLIENT_ID = "mnemos-web"
KID = "test-signing-key"


# ------------------------------------------------------------------ fakes


class FakeUserDirectory:
    """In-memory `app_user` reads, keyed the way the SQL adapter keys them."""

    def __init__(self, *users: UserCredentialRecord) -> None:
        self._users = list(users)
        self.calls: list[tuple[OrgId, str]] = []

    async def find_by_email(self, org_id: OrgId, email: str) -> UserCredentialRecord | None:
        self.calls.append((org_id, email))
        # CITEXT compares case-insensitively; the fake must agree with the column
        # or the tests would pin behaviour the database does not have.
        return next(
            (u for u in self._users if u.org_id == org_id and u.email.lower() == email.lower()),
            None,
        )


class FakeOrgDirectory:
    def __init__(self, org: OrgRecord | None, providers: Sequence[ProviderRecord] = ()) -> None:
        self._org = org
        self._providers = list(providers)

    async def find_org(self, slug: str) -> OrgRecord | None:
        return self._org if self._org is not None and self._org.slug == slug else None

    async def find_provider(self, org_id: OrgId, slug: str) -> ProviderRecord | None:
        return next((p for p in self._providers if p.org_id == org_id and p.slug == slug), None)

    async def list_enabled_providers(self, org_id: OrgId) -> Sequence[ProviderRecord]:
        return [p for p in self._providers if p.org_id == org_id and p.is_enabled]


class FakeJwks:
    """Hands back the one key these tests sign with, whatever `kid` is asked for.

    Returning the key unconditionally is the point: it removes key *selection*
    from what the rejection tests could be passing on, so a token that fails does
    so because the signature, issuer, audience or expiry is wrong — not because
    the harness never found a key.
    """

    def __init__(self, key: PyJWK) -> None:
        self._key = key
        self.issuers: list[str] = []

    async def key_for(self, issuer: str, kid: str | None) -> PyJWK:
        self.issuers.append(issuer)
        return self._key


# --------------------------------------------------------------- fixtures


@pytest.fixture(scope="session")
def hasher() -> PasswordHasher:
    """Production argon2 parameters, not cheapened ones.

    m=64 MiB costs ~50 ms per call, and the handful of calls here is worth paying
    to prove the parameters the system actually ships with round-trip.
    """
    return PasswordHasher()


@pytest.fixture(scope="session")
def password_hash(hasher: PasswordHasher) -> str:
    import anyio

    return anyio.run(hasher.hash, PASSWORD)


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def other_key() -> rsa.RSAPrivateKey:
    """A second, untrusted key — the one a forger would have."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def public_jwk(signing_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    assert isinstance(jwk, dict)
    return {**jwk, "kid": KID, "alg": "RS256", "use": "sig"}


@pytest.fixture
def jwks(public_jwk: dict[str, Any]) -> FakeJwks:
    return FakeJwks(PyJWK(public_jwk))


@pytest.fixture
def oidc(jwks: FakeJwks) -> OidcProvider:
    return OidcProvider(
        provider_id=PROVIDER_ID,
        org_id=ORG_ID,
        config=OidcConfig.build(
            issuer_internal=ISSUER_INTERNAL,
            issuer_public=ISSUER_PUBLIC,
            client_id=CLIENT_ID,
        ),
        jwks=jwks,
    )


def mint(
    key: rsa.RSAPrivateKey,
    *,
    issuer: str = ISSUER_PUBLIC,
    azp: str | None = CLIENT_ID,
    audience: Any = "account",
    expires_in_s: int = 300,
    algorithm: str = "RS256",
    **extra: Any,
) -> str:
    """A Keycloak-shaped access token. Defaults are the genuine article; every
    rejection test changes exactly one argument, so what is under test is visible
    in the call rather than buried in a payload literal."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": issuer,
        "sub": "9f1c0b2e-keycloak-subject",
        "aud": audience,
        "exp": now + timedelta(seconds=expires_in_s),
        "iat": now,
        "email": "ada@example.test",
        "preferred_username": "ada",
        "name": "Ada Lovelace",
        **extra,
    }
    if azp is not None:
        claims["azp"] = azp
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": KID})


def _b64(value: dict[str, Any]) -> str:
    """base64url without padding — the JWS encoding, for hand-forged tokens."""
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def user(**overrides: Any) -> UserCredentialRecord:
    base: dict[str, Any] = {
        "user_id": USER_ID,
        "org_id": ORG_ID,
        "email": "ada@example.test",
        "display_name": "Ada Lovelace",
        "password_hash": None,
        "is_active": True,
    }
    return UserCredentialRecord(**{**base, **overrides})


# ----------------------------------------------------------- core.security


async def test_password_hasher_round_trips_and_rejects_a_wrong_password(
    hasher: PasswordHasher, password_hash: str
) -> None:
    assert password_hash.startswith("$argon2id$"), "must be argon2id, never bcrypt or a fast hash"
    assert await hasher.verify(password_hash, PASSWORD) is True
    assert await hasher.verify(password_hash, WRONG_PASSWORD) is False


async def test_password_hashes_are_salted(hasher: PasswordHasher) -> None:
    # Two hashes of the same password must differ, or the column is a rainbow
    # table lookup away from being plaintext.
    assert await hasher.hash(PASSWORD) != await hasher.hash(PASSWORD)


async def test_password_hasher_denies_rather_than_raises_on_a_corrupt_hash(
    hasher: PasswordHasher,
) -> None:
    # One bad row must not be able to break authentication with a 500.
    assert await hasher.verify("not-a-hash", PASSWORD) is False
    assert await hasher.verify(None, PASSWORD) is False


def test_refresh_token_digest_is_sha256_and_compared_in_constant_time() -> None:
    # High-entropy secrets hash with SHA-256 so the column stays searchable by a
    # unique index; see the docstring on `digest_token`.
    digest = digest_token("a-256-bit-random-refresh-token")
    assert len(digest) == 64
    assert digest == digest_token("a-256-bit-random-refresh-token")
    assert tokens_equal(digest, digest) is True
    assert tokens_equal(digest, digest_token("different")) is False


# -------------------------------------------------------- internal provider


async def test_internal_provider_verifies_correct_password_and_rejects_wrong(
    hasher: PasswordHasher, password_hash: str
) -> None:
    directory = FakeUserDirectory(user(password_hash=password_hash))
    provider = InternalProvider(
        provider_id=PROVIDER_ID, org_id=ORG_ID, users=directory, hasher=hasher
    )

    subject = await provider.authenticate(email="ada@example.test", password=PASSWORD)
    assert subject.user_id == USER_ID
    assert subject.org_id == ORG_ID
    assert subject.provider_kind is ProviderKind.INTERNAL
    assert subject.external_subject is None  # local auth names a local user

    with pytest.raises(AuthenticationError) as denial:
        await provider.authenticate(email="ada@example.test", password=WRONG_PASSWORD)
    assert denial.value.message == AUTHENTICATION_FAILED


async def test_internal_provider_rejects_user_with_no_password_hash(
    hasher: PasswordHasher,
) -> None:
    """A Keycloak-provisioned user has `password_hash IS NULL`. Treating that as
    "no password required" would make every external user an open account."""
    directory = FakeUserDirectory(user(password_hash=None))
    provider = InternalProvider(
        provider_id=PROVIDER_ID, org_id=ORG_ID, users=directory, hasher=hasher
    )
    with pytest.raises(AuthenticationError):
        await provider.authenticate(email="ada@example.test", password=PASSWORD)
    # And the empty string is not a password either.
    with pytest.raises(AuthenticationError):
        await provider.authenticate(email="ada@example.test", password="")


async def test_internal_provider_rejects_an_inactive_user(
    hasher: PasswordHasher, password_hash: str
) -> None:
    directory = FakeUserDirectory(user(password_hash=password_hash, is_active=False))
    provider = InternalProvider(
        provider_id=PROVIDER_ID, org_id=ORG_ID, users=directory, hasher=hasher
    )
    with pytest.raises(AuthenticationError):
        await provider.authenticate(email="ada@example.test", password=PASSWORD)


async def test_internal_provider_denials_are_indistinguishable(
    hasher: PasswordHasher, password_hash: str
) -> None:
    """Unknown user, no hash, and wrong password must read identically.

    Only the message is asserted, not the timing — a wall-clock assertion is
    flaky on a shared runner. The timing defence is structural instead: the
    no-such-user path calls `verify(None, ...)`, which performs a real argon2
    verification. That call is what this test protects; deleting it leaves this
    assertion passing, so the reason is written here rather than only in the code.
    """
    directory = FakeUserDirectory(user(password_hash=password_hash), user(email="x@example.test"))
    provider = InternalProvider(
        provider_id=PROVIDER_ID, org_id=ORG_ID, users=directory, hasher=hasher
    )
    messages = set()
    for email, password in (
        ("nobody@example.test", PASSWORD),
        ("x@example.test", PASSWORD),
        ("ada@example.test", WRONG_PASSWORD),
    ):
        with pytest.raises(AuthenticationError) as denial:
            await provider.authenticate(email=email, password=password)
        messages.add(denial.value.message)
    assert messages == {AUTHENTICATION_FAILED}


async def test_internal_provider_scopes_its_lookup_to_its_own_org(
    hasher: PasswordHasher, password_hash: str
) -> None:
    """The org is bound at construction, so a provider cannot be asked about another."""
    directory = FakeUserDirectory(user(password_hash=password_hash))
    other_org = OrgId(uuid4())
    provider = InternalProvider(
        provider_id=PROVIDER_ID, org_id=other_org, users=directory, hasher=hasher
    )
    with pytest.raises(AuthenticationError):
        await provider.authenticate(email="ada@example.test", password=PASSWORD)
    assert directory.calls == [(other_org, "ada@example.test")]


# ------------------------------------------------------------ oidc provider


async def test_oidc_provider_accepts_a_genuine_token(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey, jwks: FakeJwks
) -> None:
    """The control. Every rejection below is one mutation away from this token."""
    subject = await oidc.authenticate(token=mint(signing_key))

    assert subject.org_id == ORG_ID
    assert subject.provider_kind is ProviderKind.OIDC
    assert subject.external_subject == "9f1c0b2e-keycloak-subject"
    assert subject.email == "ada@example.test"
    assert subject.display_name == "Ada Lovelace"
    # No local user is resolved here: mapping a `sub` to an `app_user` (and
    # whether to provision one) is the application layer's decision.
    assert subject.user_id is None
    # JWKS is always fetched over the internal issuer, never the token's `iss`.
    assert jwks.issuers == [ISSUER_INTERNAL]


async def test_oidc_provider_accepts_a_token_minted_through_the_public_issuer(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey
) -> None:
    """Split horizon: the browser's token says `localhost`, the API talks to
    `keycloak`. Both are configured by us; neither is read from the token."""
    assert await oidc.authenticate(token=mint(signing_key, issuer=ISSUER_PUBLIC))
    assert await oidc.authenticate(token=mint(signing_key, issuer=ISSUER_INTERNAL))
    # Trailing slashes are the same issuer, not a different one.
    assert await oidc.authenticate(token=mint(signing_key, issuer=ISSUER_PUBLIC + "/"))


async def test_oidc_provider_rejects_token_with_wrong_issuer(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey
) -> None:
    for issuer in (
        "http://evil.test/realms/mnemos",
        "http://keycloak:8080/realms/other",
        "",
    ):
        with pytest.raises(AuthenticationError) as denial:
            await oidc.authenticate(token=mint(signing_key, issuer=issuer))
        assert denial.value.message == AUTHENTICATION_FAILED


async def test_oidc_provider_rejects_token_with_bad_signature(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey, other_key: rsa.RSAPrivateKey
) -> None:
    # Signed by a key that is not in the JWKS.
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=mint(other_key))
    # Genuine token, payload edited afterwards.
    header, _, signature = mint(signing_key).split(".")
    tampered = mint(signing_key, sub="somebody-else").split(".")[1]
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=f"{header}.{tampered}.{signature}")


async def test_oidc_provider_rejects_token_that_is_expired(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey
) -> None:
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=mint(signing_key, expires_in_s=-1))


async def test_oidc_provider_rejects_an_unsigned_token(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey
) -> None:
    """`alg: none`, and the RS256→HS256 confusion attack.

    The second is the subtle one: the attacker signs with the *public* key as an
    HMAC secret. It works against any validator that reads the algorithm from the
    token, which is why the allow-list is asymmetric-only and is passed to the
    decoder rather than derived from the header.
    """
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER_PUBLIC,
        "sub": "attacker",
        "azp": CLIENT_ID,
        "exp": now + timedelta(seconds=300),
    }
    unsigned = jwt.encode(claims, key="", algorithm="none", headers={"kid": KID})
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=unsigned)

    # Forged by hand: PyJWT refuses to *mint* an HMAC token from a PEM public
    # key, which is a defence on the signing side and no help at all on the
    # verifying side — an attacker is not using PyJWT to build the forgery.
    public_pem = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    header = _b64({"alg": "HS256", "typ": "JWT", "kid": KID})
    payload = _b64({**claims, "exp": int(claims["exp"].timestamp())})
    signing_input = f"{header}.{payload}".encode()
    signature = (
        base64.urlsafe_b64encode(hmac.new(public_pem, signing_input, hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=f"{header}.{payload}.{signature}")


async def test_oidc_provider_rejects_a_token_issued_to_another_client(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey
) -> None:
    """Right realm, right key, wrong client. A valid signature over claims that
    were never meant for us."""
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=mint(signing_key, azp="some-other-client"))
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=mint(signing_key, azp=None, audience="account"))
    # `aud` naming us is equally acceptable — that is an ID token's shape.
    assert await oidc.authenticate(token=mint(signing_key, azp=None, audience=CLIENT_ID))
    assert await oidc.authenticate(
        token=mint(signing_key, azp=None, audience=["account", CLIENT_ID])
    )


async def test_oidc_provider_rejects_a_token_with_no_expiry(
    oidc: OidcProvider, signing_key: rsa.RSAPrivateKey
) -> None:
    """A missing claim is a refusal, not a default. PyJWT does not verify an
    `exp` it cannot find, so `require` is what makes the expiry check mandatory."""
    claims = {"iss": ISSUER_PUBLIC, "sub": "ada", "azp": CLIENT_ID}
    token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KID})
    with pytest.raises(AuthenticationError):
        await oidc.authenticate(token=token)


async def test_oidc_provider_rejects_garbage(oidc: OidcProvider) -> None:
    for junk in ("", "not.a.token", "a.b", "Bearer eyJ"):
        with pytest.raises(AuthenticationError):
            await oidc.authenticate(token=junk)


# -------------------------------------------------------------- jwks cache


def discovery_document(issuer: str = ISSUER_INTERNAL, **overrides: Any) -> dict[str, Any]:
    """The subset of Keycloak's `/.well-known/openid-configuration` that is used.

    Shaped like the real one rather than trimmed to whatever the test under the
    cursor happens to read, so a new required endpoint fails the fixture honestly
    instead of passing against a document Keycloak would never send.
    """
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/protocol/openid-connect/auth",
        "token_endpoint": f"{issuer}/protocol/openid-connect/token",
        "jwks_uri": f"{issuer}/protocol/openid-connect/certs",
        **overrides,
    }


def _jwks_transport(document: dict[str, Any], counter: list[int]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=discovery_document())
        counter[0] += 1
        return httpx.Response(200, json=document)

    return httpx.MockTransport(handle)


async def test_jwks_is_fetched_once_and_cached_within_its_ttl(
    public_jwk: dict[str, Any],
) -> None:
    """Re-fetching per request would put the IdP on the critical path of every
    authenticated call."""
    fetches = [0]
    transport = _jwks_transport({"keys": [public_jwk]}, fetches)
    async with httpx.AsyncClient(transport=transport) as client:
        cache = HttpJwksCache(client=client, ttl_s=900)
        for _ in range(5):
            key = await cache.key_for(ISSUER_INTERNAL, KID)
            assert key.key_id == KID
    assert fetches == [1]


async def test_jwks_refetches_for_an_unknown_kid_but_not_unboundedly(
    public_jwk: dict[str, Any],
) -> None:
    """Key rotation must be picked up without a restart; an unknown `kid` is also
    what a forged token carries, so the re-fetch is rate limited."""
    fetches = [0]
    transport = _jwks_transport({"keys": [public_jwk]}, fetches)
    async with httpx.AsyncClient(transport=transport) as client:
        cache = HttpJwksCache(client=client, ttl_s=900, min_refetch_interval_s=0.0)
        await cache.key_for(ISSUER_INTERNAL, KID)
        assert fetches == [1]
        with pytest.raises(AuthenticationError):
            await cache.key_for(ISSUER_INTERNAL, "a-kid-that-does-not-exist")
        assert fetches == [2], "an unknown kid triggers exactly one re-fetch"

        # With the floor in force, a storm of forged kids costs no extra fetches.
        cache = HttpJwksCache(client=client, ttl_s=900, min_refetch_interval_s=3600.0)
        await cache.key_for(ISSUER_INTERNAL, KID)
        before = fetches[0]
        for _ in range(10):
            with pytest.raises(AuthenticationError):
                await cache.key_for(ISSUER_INTERNAL, "forged")
        assert fetches[0] == before


@pytest.mark.parametrize(
    "endpoint",
    ["jwks_uri", "authorization_endpoint", "token_endpoint"],
)
async def test_a_discovered_endpoint_outside_the_issuer_is_refused(
    public_jwk: dict[str, Any], endpoint: str
) -> None:
    """The discovery document comes from the IdP but is still remote input.

    Every endpoint is constrained, not just `jwks_uri`: a redirected
    `authorization_endpoint` is a phishing page wearing our login, and a
    redirected `token_endpoint` is where the authorization code gets posted.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=discovery_document(**{endpoint: "http://evil.test/x"}))
        return httpx.Response(200, json={"keys": [public_jwk]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        cache = HttpJwksCache(client=client, ttl_s=900)
        with pytest.raises(AuthenticationError):
            await cache.key_for(ISSUER_INTERNAL, KID)


async def test_discovery_is_cached_and_shared_between_callers() -> None:
    """The login flow and the JWKS cache both need it; one document serves both."""
    discoveries = [0]

    def handle(request: httpx.Request) -> httpx.Response:
        discoveries[0] += 1
        return httpx.Response(200, json=discovery_document())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        metadata = HttpOidcMetadata(client=client, ttl_s=900)
        for _ in range(4):
            found = await metadata.metadata_for(ISSUER_INTERNAL)
            assert found.token_endpoint == f"{ISSUER_INTERNAL}/protocol/openid-connect/token"
        assert discoveries == [1]
        # A trailing slash is the same issuer, not a second cache entry.
        await metadata.metadata_for(ISSUER_INTERNAL + "/")
        assert discoveries == [1]


async def test_the_browser_is_sent_to_the_public_issuer() -> None:
    """Split horizon in one assertion: discovery runs over `keycloak:8080`, the
    redirect the browser follows must say `localhost:8080` or it cannot resolve."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert "keycloak" in str(request.url), "discovery must use the internal issuer"
        return httpx.Response(200, json=discovery_document())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        metadata = await HttpOidcMetadata(client=client, ttl_s=900).metadata_for(ISSUER_INTERNAL)

    public = public_authorization_endpoint(metadata, ISSUER_PUBLIC)
    assert public == f"{ISSUER_PUBLIC}/protocol/openid-connect/auth"
    assert "keycloak:8080" not in public
    # The path is preserved exactly; only the host moves.
    assert public.endswith("/protocol/openid-connect/auth")


async def test_jwks_fetch_failure_is_a_denial_not_a_crash() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="keycloak is down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        cache = HttpJwksCache(client=client, ttl_s=900)
        with pytest.raises(AuthenticationError):
            await cache.key_for(ISSUER_INTERNAL, KID)


# ------------------------------------------------------------------ factory


def _org(**overrides: Any) -> OrgRecord:
    base: dict[str, Any] = {
        "org_id": ORG_ID,
        "slug": "acme",
        "is_active": True,
        "default_provider_slug": None,
    }
    return OrgRecord(**{**base, **overrides})


def _provider(**overrides: Any) -> ProviderRecord:
    base: dict[str, Any] = {
        "provider_id": PROVIDER_ID,
        "org_id": ORG_ID,
        "slug": "internal",
        "kind": "internal",
        "is_enabled": True,
        "issuer_public": None,
        "issuer_internal": None,
        "client_id": None,
    }
    return ProviderRecord(**{**base, **overrides})


def _oidc_provider(**overrides: Any) -> ProviderRecord:
    return _provider(
        **{
            "slug": "keycloak",
            "kind": "oidc",
            "issuer_public": ISSUER_PUBLIC,
            "issuer_internal": ISSUER_INTERNAL,
            "client_id": CLIENT_ID,
            **overrides,
        }
    )


def _factory(
    org: OrgRecord | None,
    providers: Sequence[ProviderRecord],
    hasher: PasswordHasher,
    jwks: FakeJwks,
) -> ProviderFactory:
    return ProviderFactory(
        orgs=FakeOrgDirectory(org, providers),
        users=FakeUserDirectory(),
        hasher=hasher,
        jwks=jwks,
    )


async def test_factory_returns_the_strategy_named_by_the_identity_provider_row(
    hasher: PasswordHasher, jwks: FakeJwks
) -> None:
    factory = _factory(_org(), [_provider(), _oidc_provider()], hasher, jwks)

    internal = await factory.for_org("acme", "internal")
    assert isinstance(internal, InternalProvider)
    assert internal.kind is ProviderKind.INTERNAL
    assert isinstance(internal, CredentialAuthProvider)

    oidc = await factory.for_org("acme", "keycloak")
    assert isinstance(oidc, OidcProvider)
    assert oidc.kind is ProviderKind.OIDC
    assert isinstance(oidc, TokenAuthProvider)


async def test_factory_denies_an_unknown_or_disabled_provider(
    hasher: PasswordHasher, jwks: FakeJwks
) -> None:
    factory = _factory(
        _org(), [_provider(), _oidc_provider(slug="keycloak", is_enabled=False)], hasher, jwks
    )
    for slug in ("keycloak", "saml", "does-not-exist"):
        with pytest.raises(AuthenticationError) as denial:
            await factory.for_org("acme", slug)
        assert denial.value.message == AUTHENTICATION_FAILED


async def test_factory_denies_an_unknown_or_inactive_org(
    hasher: PasswordHasher, jwks: FakeJwks
) -> None:
    """A caller that is not yet authenticated must not learn which orgs exist."""
    with pytest.raises(AuthenticationError):
        await _factory(_org(), [_provider()], hasher, jwks).for_org("no-such-org", "internal")
    with pytest.raises(AuthenticationError):
        await _factory(_org(is_active=False), [_provider()], hasher, jwks).for_org(
            "acme", "internal"
        )


async def test_factory_denies_a_kind_it_does_not_recognise(
    hasher: PasswordHasher, jwks: FakeJwks
) -> None:
    """Including `api_key`, which is a real `ProviderKind` but not a login
    strategy — API keys authenticate against `api_key` in M3.5."""
    for kind in ("api_key", "saml", "ldap", ""):
        factory = _factory(_org(), [_provider(slug="p", kind=kind)], hasher, jwks)
        with pytest.raises(AuthenticationError):
            await factory.for_org("acme", "p")


async def test_factory_denies_an_oidc_row_with_incomplete_configuration(
    hasher: PasswordHasher, jwks: FakeJwks
) -> None:
    """Without a client id the audience check cannot run; without an issuer there
    is nothing to trust. Neither may be carried in as `None` to fail later."""
    for broken in (
        _oidc_provider(issuer_internal=None),
        _oidc_provider(client_id=None),
    ):
        factory = _factory(_org(), [broken], hasher, jwks)
        with pytest.raises(AuthenticationError):
            await factory.for_org("acme", "keycloak")


async def test_factory_uses_the_orgs_default_when_no_provider_is_named(
    hasher: PasswordHasher, jwks: FakeJwks
) -> None:
    factory = _factory(
        _org(default_provider_slug="keycloak"), [_provider(), _oidc_provider()], hasher, jwks
    )
    assert isinstance(await factory.for_org("acme"), OidcProvider)


async def test_factory_falls_back_to_a_sole_enabled_provider_but_refuses_to_guess(
    hasher: PasswordHasher, jwks: FakeJwks
) -> None:
    """One enabled provider is unambiguous. Two, with no default, is a guess — and
    guessing is how a stronger provider is silently bypassed for a weaker one."""
    sole = _factory(_org(), [_provider()], hasher, jwks)
    assert isinstance(await sole.for_org("acme"), InternalProvider)

    ambiguous = _factory(_org(), [_provider(), _oidc_provider()], hasher, jwks)
    with pytest.raises(AuthenticationError):
        await ambiguous.for_org("acme")

    none_enabled = _factory(_org(), [_provider(is_enabled=False)], hasher, jwks)
    with pytest.raises(AuthenticationError):
        await none_enabled.for_org("acme")


# ----------------------------------------------------------------- layering


def test_authenticated_subject_must_name_somebody() -> None:
    with pytest.raises(ValueError, match="local user id or an external subject"):
        AuthenticatedSubject(
            org_id=ORG_ID, provider_id=PROVIDER_ID, provider_kind=ProviderKind.OIDC
        )


def test_providers_import_no_sqlalchemy_and_no_fastapi() -> None:
    """The provider layer reaches persistence through ports and knows no HTTP.

    Run in a fresh interpreter for the same reason M3.1's equivalent is: inside
    the pytest process both packages are already imported by other test modules,
    so an in-process `sys.modules` check would pass without proving anything.

    SQLAlchemy is the stronger of the two claims — it is what makes these tests
    hermetic — and FastAPI is what keeps M3.3's routes from leaking back into the
    strategies.
    """
    proof = (
        "import sys; import mnemos.features.identity.providers as p; "
        "leaked = [m for m in ('sqlalchemy', 'fastapi') if m in sys.modules]; "
        "assert not leaked, f'identity.providers must not import {leaked}'; "
        "assert p.ProviderFactory is not None"
    )
    result = subprocess.run(
        [sys.executable, "-c", proof], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_a_denial_carries_its_reason_to_the_log_and_not_to_the_caller() -> None:
    """Two audiences, one exception: `message` crosses the API boundary, `details`
    goes to the log (CodingStandards §4)."""
    from mnemos.features.identity.providers import denied

    error = denied("password mismatch")
    assert error.message == AUTHENTICATION_FAILED
    assert error.details == {"reason": "password mismatch"}
    assert error.status_code == 401
    assert "password mismatch" not in str(error)


def test_monotonic_clock_is_used_for_cache_expiry() -> None:
    """A wall-clock jump backwards must not extend a JWKS cache entry past its
    TTL. `time.monotonic` is the property; this pins the import that provides it."""
    import mnemos.features.identity.providers.oidc as oidc_module

    assert oidc_module.time.monotonic is time.monotonic
