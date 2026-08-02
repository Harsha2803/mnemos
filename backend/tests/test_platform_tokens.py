"""M3.4 — the access tokens Mnemos mints for itself.

Hermetic: no Docker, no network. Signing and verifying are properties of *this*
code, not of Postgres or of Keycloak, so a container would make these slower and
no more true. (Contrast `test_tenant_isolation.py`, where a fake would only prove
that the fake isolates.)

`test_a_genuine_access_token_is_accepted` runs first and everything else is one
mutation away from it. That ordering is not cosmetic: a verifier that rejects
every token passes all six rejection tests, and M3.2 already recorded the lesson
next to `test_oidc_provider_accepts_a_genuine_token`.

The forgeries are hand-built from `base64`/`hmac` rather than minted with PyJWT,
for the reason M3.2's `test_oidc_provider_rejects_an_unsigned_token` gives: PyJWT
refuses to *produce* some of them, which is a defence on the signing side and no
help at all on the verifying side. An attacker is not using our library.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest

from mnemos.core.clock import FrozenClock
from mnemos.core.errors import AuthenticationError, ConfigurationError
from mnemos.core.ids import Uuid7Generator
from mnemos.features.identity.domain import (
    ACCESS_TOKEN_CLAIMS,
    FORBIDDEN_CLAIMS,
    AccessTokenClaims,
    OrgId,
    RefreshCredential,
    SessionId,
    UserId,
)
from mnemos.features.identity.providers import (
    ALLOWED_PLATFORM_ALGORITHMS,
    AUTHENTICATION_FAILED,
    PlatformTokenCodec,
    PlatformTokenConfig,
)

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
OTHER_SECRET = "a-different-thirty-two-byte-signing-secret"
ISSUER = "mnemos"
TTL_S = 900

ORG_ID = OrgId(uuid4())
USER_ID = UserId(uuid4())
SESSION_ID = SessionId(uuid4())

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def codec(clock: FrozenClock) -> PlatformTokenCodec:
    return PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER, access_ttl_s=TTL_S),
        clock=clock,
        ids=Uuid7Generator(),
    )


def _b64(value: dict[str, Any]) -> str:
    """base64url without padding — the JWS segment encoding."""
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _genuine_payload() -> dict[str, Any]:
    """The claims of a valid token, as a plain dict, for hand-forging."""
    return {
        "sub": str(USER_ID),
        "org": str(ORG_ID),
        "sid": str(SESSION_ID),
        "jti": str(uuid4()),
        "iss": ISSUER,
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(seconds=TTL_S)).timestamp()),
    }


def _forge(header: dict[str, Any], payload: dict[str, Any], *, secret: bytes | None) -> str:
    """Hand-build a compact JWS. ``secret=None`` produces an empty signature."""
    parts = f"{_b64(header)}.{_b64(payload)}"
    if secret is None:
        return f"{parts}."
    digest = hmac.new(secret, parts.encode(), hashlib.sha256).digest()
    return f"{parts}.{base64.urlsafe_b64encode(digest).rstrip(b'=').decode()}"


# ----------------------------------------------------------------- the control


def test_a_genuine_access_token_is_accepted(codec: PlatformTokenCodec) -> None:
    """Without this, the six rejections below prove nothing."""
    token, minted = codec.mint(subject=USER_ID, org_id=ORG_ID, session_id=SESSION_ID)
    verified = codec.verify(token)

    assert verified == minted
    assert verified.subject == USER_ID
    assert verified.org_id == ORG_ID
    assert verified.session_id == SESSION_ID
    assert verified.issuer == ISSUER
    assert verified.issued_at == NOW
    assert verified.expires_at == NOW + timedelta(seconds=TTL_S)


def test_the_access_token_lifetime_is_fifteen_minutes(codec: PlatformTokenCodec) -> None:
    """`APIContract.md` §2. Short because the token cannot be revoked mid-life —
    the refresh chain is what revocation acts on."""
    _, claims = codec.mint(subject=USER_ID, org_id=ORG_ID, session_id=SESSION_ID)
    assert claims.expires_at - claims.issued_at == timedelta(minutes=15)
    assert codec.access_ttl_s == 900


def test_every_token_gets_its_own_jti(codec: PlatformTokenCodec) -> None:
    """A reused `jti` makes a future replay-suppression list useless, and it is
    the kind of thing that only shows up under load."""
    ids = {
        codec.mint(subject=USER_ID, org_id=ORG_ID, session_id=SESSION_ID)[1].token_id
        for _ in range(20)
    }
    assert len(ids) == 20


# ------------------------------------------------------------ the M3.4 criteria


def test_access_token_carries_no_roles_or_permissions(codec: PlatformTokenCodec) -> None:
    """The decoded claims, inspected directly — not the type, the wire bytes.

    A token carrying `roles` keeps working for its whole lifetime after the role
    is revoked. `APIContract.md` §2 pays a database read per request to avoid
    exactly that, and this is the assertion that the payment is actually made.
    """
    token, _ = codec.mint(subject=USER_ID, org_id=ORG_ID, session_id=SESSION_ID)

    # Decoded without any verification: what is asserted is the *content* of the
    # token as an attacker or a debugger would read it, not what our own parser
    # chooses to expose.
    payload = jwt.decode(token, options={"verify_signature": False})

    assert set(payload) == set(ACCESS_TOKEN_CLAIMS), (
        "an access token carries identity and nothing else"
    )
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in payload
    # And nothing that merely *looks* like authority under another name.
    assert not any("role" in k or "perm" in k or "scope" in k for k in payload)


def test_a_token_that_smuggles_authorization_claims_is_rejected(
    codec: PlatformTokenCodec,
) -> None:
    """Enforced on the way in as well as on the way out.

    Minting is ours to control today; verification is what protects against a
    later code path that helpfully attaches a `scope`, or against a token minted
    by a sibling service that shares the secret and not the discipline.
    """
    for claim in ("roles", "permissions", "scope", "realm_access"):
        forged = jwt.encode({**_genuine_payload(), claim: ["admin"]}, SECRET, algorithm="HS256")
        with pytest.raises(AuthenticationError) as denial:
            codec.verify(forged)
        assert denial.value.message == AUTHENTICATION_FAILED


# PyJWT warns that the test secret is short for HS384/HS512. It is, deliberately:
# those tokens exist only to be refused, and lengthening the secret to silence a
# warning about a forgery would be theatre.
@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
def test_a_token_signed_with_another_algorithm_is_rejected(
    codec: PlatformTokenCodec,
) -> None:
    """Including `alg: none`, hand-forged.

    `alg: none` is the forgery that works against any validator polite enough to
    do what the token's header asks. HS512 and RS256 are the substitution cases:
    a validator that derives its algorithm from the header can be steered into a
    different verification path, and under HMAC the interesting one is a *longer*
    HMAC that a naive `algorithms=[header['alg']]` would happily accept.
    """
    payload = _genuine_payload()

    # 1. `alg: none`, with an empty signature — the canonical unsigned token.
    for header in ({"alg": "none", "typ": "JWT"}, {"alg": "None", "typ": "JWT"}):
        with pytest.raises(AuthenticationError):
            codec.verify(_forge(header, payload, secret=None))

    # 2. `alg: none` with a signature attached anyway, in case a validator only
    #    checks that *something* is there.
    with pytest.raises(AuthenticationError):
        codec.verify(_forge({"alg": "none", "typ": "JWT"}, payload, secret=b"anything"))

    # 3. A genuinely-signed token under an algorithm we do not allow. PyJWT will
    #    mint these, and they are correct HMACs under our real secret — only the
    #    allow-list refuses them.
    for algorithm in ("HS384", "HS512"):
        with pytest.raises(AuthenticationError):
            codec.verify(jwt.encode(payload, SECRET, algorithm=algorithm))

    # 4. The header lies about the algorithm: an HS256 body signed with HS256,
    #    relabelled. The signature is right, the label is wrong, and the
    #    allow-list means the label was never consulted in the first place.
    signed = _forge({"alg": "HS512", "typ": "JWT"}, payload, secret=SECRET.encode())
    with pytest.raises(AuthenticationError):
        codec.verify(signed)

    # 5. And the control, again, so this test cannot pass by rejecting everything.
    assert codec.verify(jwt.encode(payload, SECRET, algorithm="HS256"))


def test_a_token_signed_with_another_secret_is_rejected(codec: PlatformTokenCodec) -> None:
    """The signature is the only thing standing between a caller and any `sub`
    they care to write."""
    forged = jwt.encode({**_genuine_payload(), "sub": str(uuid4())}, OTHER_SECRET, "HS256")
    with pytest.raises(AuthenticationError):
        codec.verify(forged)

    # Genuine token, payload swapped afterwards for one signed with the same key
    # but different claims — the signature no longer covers the body it is next to.
    genuine, _ = codec.mint(subject=USER_ID, org_id=ORG_ID, session_id=SESSION_ID)
    header, _, signature = genuine.split(".")
    other, _ = codec.mint(subject=UserId(uuid4()), org_id=ORG_ID, session_id=SESSION_ID)
    with pytest.raises(AuthenticationError):
        codec.verify(f"{header}.{other.split('.')[1]}.{signature}")


def test_expired_access_token_is_rejected(codec: PlatformTokenCodec, clock: FrozenClock) -> None:
    """Zero leeway, asserted at the boundary second rather than a minute past it.

    A `leeway` that quietly forgives clock skew is the difference between a
    15-minute token and a 15-minute-plus-whatever token, and the whole security
    argument for a short-lived bearer credential is its expiry.
    """
    token, claims = codec.mint(subject=USER_ID, org_id=ORG_ID, session_id=SESSION_ID)

    # One second before expiry: still good.
    clock.advance(seconds=TTL_S - 1)
    assert codec.verify(token).token_id == claims.token_id

    # The instant it expires, and every instant after.
    clock.advance(seconds=1)
    with pytest.raises(AuthenticationError) as denial:
        codec.verify(token)
    assert denial.value.message == AUTHENTICATION_FAILED
    assert "expired" in denial.value.details["reason"], "the log gets the real reason"

    clock.advance(days=1)
    with pytest.raises(AuthenticationError):
        codec.verify(token)


def test_a_token_from_another_issuer_is_rejected(codec: PlatformTokenCodec) -> None:
    """`iss` is compared against the value we configured, never against itself.

    This is what stops a token from a *different Mnemos deployment* that shares a
    leaked secret — a staging environment, say — from authenticating here.
    """
    for issuer in ("mnemos-staging", "", "https://evil.test"):
        forged = jwt.encode({**_genuine_payload(), "iss": issuer}, SECRET, algorithm="HS256")
        with pytest.raises(AuthenticationError):
            codec.verify(forged)


def test_a_token_missing_a_required_claim_is_rejected(codec: PlatformTokenCodec) -> None:
    """A missing claim is a refusal, not a default.

    `exp` is the one that matters — PyJWT does not verify an expiry it cannot
    find, so without `require` an `exp`-less token is immortal — but `org` and
    `sid` are just as load-bearing: a token with no org authenticates into no
    tenant, and the code downstream would have to invent one.
    """
    for omitted in ACCESS_TOKEN_CLAIMS:
        payload = {k: v for k, v in _genuine_payload().items() if k != omitted}
        forged = jwt.encode(payload, SECRET, algorithm="HS256")
        with pytest.raises(AuthenticationError):
            codec.verify(forged)


def test_a_token_with_unparseable_claims_is_rejected(codec: PlatformTokenCodec) -> None:
    """Right signature, wrong shapes. A valid HMAC over nonsense is still nonsense.

    Forged by hand rather than with ``jwt.encode``, because PyJWT refuses to mint
    a non-string ``iss`` — the same signing-side courtesy that made M3.2's
    HS256-confusion token unmintable, and the same reason it is no defence: the
    forgery has to be built the way an attacker would build it.
    """
    for bad in (
        {"sub": "not-a-uuid"},
        {"org": 12},
        {"sid": None},
        {"iat": "yesterday"},
        {"exp": "never"},
        {"iss": 7},
    ):
        forged = _forge(
            {"alg": "HS256", "typ": "JWT"},
            {**_genuine_payload(), **bad},
            secret=SECRET.encode(),
        )
        with pytest.raises(AuthenticationError) as denial:
            codec.verify(forged)
        assert denial.value.message == AUTHENTICATION_FAILED


def test_garbage_is_a_denial_not_a_crash(codec: PlatformTokenCodec) -> None:
    for junk in ("", "not.a.token", "a.b", "Bearer eyJ", "..", "eyJ"):
        with pytest.raises(AuthenticationError) as denial:
            codec.verify(junk)
        assert denial.value.message == AUTHENTICATION_FAILED


# ------------------------------------------------------------------ the config


def test_the_codec_refuses_to_be_built_with_an_unusable_secret() -> None:
    """Fail at startup, not at the first login (CodingStandards §7)."""
    with pytest.raises(ConfigurationError):
        PlatformTokenConfig(secret="too-short", issuer=ISSUER)
    with pytest.raises(ConfigurationError):
        PlatformTokenConfig(secret=SECRET, issuer="")
    with pytest.raises(ConfigurationError):
        PlatformTokenConfig(secret=SECRET, issuer=ISSUER, access_ttl_s=0)


def test_the_algorithm_allow_list_is_symmetric_and_singular() -> None:
    """A one-element allow-list is the whole defence; widening it is the change
    that reintroduces algorithm substitution, so pin the shape.

    Asymmetric entries would be wrong here for the *opposite* reason they are
    right in `oidc.py`: there we are only ever the verifier, here we are also the
    signer. See `docs/ThreatModel.md` §5.1.
    """
    assert ALLOWED_PLATFORM_ALGORITHMS == ("HS256",)
    with pytest.raises(ConfigurationError):
        PlatformTokenConfig(secret=SECRET, issuer=ISSUER, algorithm="EdDSA")
    with pytest.raises(ConfigurationError):
        PlatformTokenConfig(secret=SECRET, issuer=ISSUER, algorithm="none")


def test_neither_the_config_nor_the_credentials_print_their_secrets() -> None:
    """`repr` runs in log formatting, in exception chaining and in every debugger
    frame. A dataclass that prints a bearer secret leaks it everywhere at once."""
    config = PlatformTokenConfig(secret=SECRET, issuer=ISSUER)
    assert SECRET not in repr(config)
    credential = RefreshCredential(org_slug="acme", secret="s3cr3t-and-high-entropy")
    assert "s3cr3t" not in repr(credential)
    assert credential.render() == "acme.s3cr3t-and-high-entropy"


# ------------------------------------------------------------------- the claims


def test_access_token_claims_reject_a_naive_or_backwards_lifetime() -> None:
    """A naive datetime becomes an `exp` in whatever zone the server happens to
    run in, which is an expiry check that is hours wrong in one direction."""
    with pytest.raises(ValueError, match="timezone-aware"):
        AccessTokenClaims(
            subject=USER_ID,
            org_id=ORG_ID,
            session_id=SESSION_ID,
            token_id=uuid4(),
            issuer=ISSUER,
            issued_at=datetime(2026, 8, 2, 12, 0),  # noqa: DTZ001 - the thing under test
            expires_at=NOW + timedelta(minutes=15),
        )
    with pytest.raises(ValueError, match="expire after"):
        AccessTokenClaims(
            subject=USER_ID,
            org_id=ORG_ID,
            session_id=SESSION_ID,
            token_id=uuid4(),
            issuer=ISSUER,
            issued_at=NOW,
            expires_at=NOW,
        )


def test_refresh_credential_splits_on_the_last_separator() -> None:
    """The secret is base64url and can never contain a `.`; an org slug might."""
    assert RefreshCredential.parse("acme.abc-123") == RefreshCredential("acme", "abc-123")
    assert RefreshCredential.parse("a.b.secret") == RefreshCredential("a.b", "secret")
    for malformed in ("", "no-separator", ".secret", "org."):
        with pytest.raises(ValueError, match="refresh credential"):
            RefreshCredential.parse(malformed)


def test_the_claim_round_trip_is_lossless() -> None:
    """`to_claims` and `from_claims` are the two halves of the wire format; if
    they drift, a token this system minted stops verifying against itself."""
    claims = AccessTokenClaims(
        subject=USER_ID,
        org_id=ORG_ID,
        session_id=SESSION_ID,
        token_id=UUID("018f2b7c-0000-7000-8000-000000000001"),
        issuer=ISSUER,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=TTL_S),
    )
    assert AccessTokenClaims.from_claims(claims.to_claims()) == claims


# ----------------------------------------------------------------- the layering


def test_the_token_domain_imports_no_sqlalchemy_no_fastapi_and_no_pyjwt() -> None:
    """`domain/` stays pure (ADAPTATION §5), and this adds a third exclusion.

    PyJWT is the interesting one: the temptation with a claims type is to give it
    an `encode()` method, which drags a crypto library and a signing secret into
    the layer that is supposed to be a vocabulary. Signing lives in
    `providers/platform.py` instead.

    A fresh interpreter, for the reason M3.1 and M3.2 give: inside the pytest
    process all three are already imported by other modules, so an in-process
    `sys.modules` check passes vacuously.
    """
    proof = (
        "import sys; import mnemos.features.identity.domain as d; "
        "leaked = [m for m in ('sqlalchemy', 'fastapi', 'jwt') if m in sys.modules]; "
        "assert not leaked, f'identity.domain must not import {leaked}'; "
        "assert d.AccessTokenClaims is not None and d.RefreshCredential is not None"
    )
    result = subprocess.run(
        [sys.executable, "-c", proof], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
