"""OIDC authentication: validating a token Keycloak minted.

This task is token *validation* only. The browser redirect and the code+PKCE
round-trip are M3.3; what is settled here is the half that decides whether a
presented token is genuine, because that is the half an attacker interacts with.

Five checks, and skipping any one of them makes the other four decorative:

1. **Signature**, against a key fetched from the IdP's JWKS — never a key or a
   secret carried in the token.
2. **Algorithm**, against a fixed allow-list passed to the decoder. The token's
   own ``alg`` header is *never* what selects the verification algorithm. That is
   the ``alg: none`` forgery and the RS256→HS256 confusion attack, where a token
   signed with the public key as an HMAC secret verifies. PyJWT requires an
   explicit ``algorithms=`` list; this module keeps that list asymmetric-only.
3. **Issuer**, against the URLs *we configured*, never against the ``iss`` inside
   the token. Comparing a token's ``iss`` to itself is a check that always passes.
4. **Audience**, against our client id — via ``aud`` or ``azp``, see below. A token
   Keycloak minted for a different client in the same realm is a valid signature
   over the wrong claims, and without this check it authenticates.
5. **Expiry**, with no leeway.

**Two trusted issuers, deliberately.** Split-horizon means the browser obtains its
token through ``issuer_public`` (``localhost:8080``) while the API fetches JWKS
over ``issuer_internal`` (``keycloak:8080``); the compose stack runs Keycloak with
``KC_HOSTNAME_STRICT=false``, so the ``iss`` it stamps is whichever host the token
was minted through. Accepting only ``issuer_internal`` would therefore reject
every token a browser could actually obtain. Both URLs are configuration we
control, so accepting either keeps the property that matters — the token's own
claim never decides — while making the containerised deployment work. This is a
documented refinement of the one-issuer wording in TRACKER §5; see TRACKER §4.

**``aud`` or ``azp``.** Keycloak puts the *resource* audience in ``aud`` (commonly
``account``) and the client the token was issued to in ``azp``. Requiring
``aud == client_id`` alone rejects ordinary Keycloak access tokens; accepting any
``aud`` accepts tokens minted for other clients. Requiring the client id in either
position is the check that means "this token was issued to us", which is the
question being asked. PyJWT's own ``aud`` verification is therefore disabled and
replaced, rather than left on and worked around.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

from mnemos.core.logging import get_logger
from mnemos.core.types import ProviderKind
from mnemos.features.identity.domain import OrgId, ProviderId
from mnemos.features.identity.providers.base import AuthenticatedSubject, denied

logger = get_logger(__name__)

#: Asymmetric only. An HMAC algorithm here would let a token signed with the
#: *public* key verify, because the public key is exactly what an attacker has.
ALLOWED_ALGORITHMS: Final[tuple[str, ...]] = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
)

#: Absent any of these, the token is not evaluable and is refused rather than
#: defaulted. `exp` in particular: PyJWT does not require a claim it does not find.
REQUIRED_CLAIMS: Final[tuple[str, ...]] = ("exp", "iss", "sub")

DISCOVERY_PATH: Final = "/.well-known/openid-configuration"
HTTP_TIMEOUT_S: Final = 5.0

#: Floor between JWKS fetches triggered by an unknown `kid`. Key rotation must be
#: picked up without a restart, but an unknown `kid` is also what a forged token
#: has — without a floor, unsigned garbage is a free request amplifier against the
#: IdP.
MIN_REFETCH_INTERVAL_S: Final = 30.0


def _normalize_issuer(issuer: str) -> str:
    """Strip the trailing slash. ``https://host/realms/x`` and ``.../x/`` are the
    same issuer, and a mismatch here is an outage that looks like an attack."""
    return issuer.rstrip("/")


class JwksSource(Protocol):
    """Supplies the verification key for a ``kid``, for one issuer."""

    async def key_for(self, issuer: str, kid: str | None) -> PyJWK: ...


class _CachedJwks:
    __slots__ = ("expires_at", "fetched_at", "keys")

    def __init__(self, keys: PyJWKSet, expires_at: float, fetched_at: float) -> None:
        self.keys = keys
        self.expires_at = expires_at
        self.fetched_at = fetched_at


class HttpJwksCache:
    """Fetches and caches JWKS over the *internal* issuer URL.

    Cached for ``oidc_jwks_cache_s``: re-fetching per request would put the IdP on
    the critical path of every authenticated call and make it a single point of
    failure for a system that otherwise only needs it at login.

    A cache with a TTL cannot, on its own, survive key rotation — the IdP signs
    with a new key and every token fails until the TTL lapses. So an unknown
    ``kid`` forces a re-fetch, rate-limited by :data:`MIN_REFETCH_INTERVAL_S`. One
    in-flight fetch per issuer, guarded by a lock, so a cold cache under
    concurrent logins produces one request rather than one per caller.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        ttl_s: int,
        timeout_s: float = HTTP_TIMEOUT_S,
        min_refetch_interval_s: float = MIN_REFETCH_INTERVAL_S,
    ) -> None:
        self._client = client
        self._ttl_s = ttl_s
        self._timeout_s = timeout_s
        self._min_refetch_interval_s = min_refetch_interval_s
        self._cache: dict[str, _CachedJwks] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def key_for(self, issuer: str, kid: str | None) -> PyJWK:
        issuer = _normalize_issuer(issuer)
        entry = self._cache.get(issuer)
        fetched_here = False

        if entry is None or time.monotonic() >= entry.expires_at:
            entry = await self._refresh(issuer, stale=entry)
            fetched_here = True

        key = self._select(entry, kid)
        if key is not None:
            return key

        # Live cache, unknown `kid`: either the IdP rotated its signing key, or
        # the token is forged. One rate-limited re-fetch distinguishes them —
        # unless this call already fetched, in which case the key genuinely is
        # not published and fetching again would learn nothing.
        if not fetched_here and time.monotonic() - entry.fetched_at >= self._min_refetch_interval_s:
            entry = await self._refresh(issuer, stale=entry)
            key = self._select(entry, kid)
            if key is not None:
                return key
        raise denied(f"no JWKS key for kid {kid!r} at {issuer}")

    @staticmethod
    def _select(entry: _CachedJwks, kid: str | None) -> PyJWK | None:
        keys = [k for k in entry.keys.keys if k.public_key_use in ("sig", None)]
        if kid is not None:
            return next((k for k in keys if k.key_id == kid), None)
        # A JWKS with exactly one key is unambiguous without a `kid`. More than
        # one and there is nothing to choose on, so refuse rather than try each:
        # trying each turns key selection into an oracle.
        return keys[0] if len(keys) == 1 else None

    async def _refresh(self, issuer: str, *, stale: _CachedJwks | None) -> _CachedJwks:
        """Fetch JWKS, collapsing concurrent callers onto one request.

        ``stale`` is the entry the caller found inadequate. Inside the lock, a
        cached entry that is *not that object* was put there by another caller
        while this one waited, so it is fresh and gets reused. Comparing identity
        rather than a time window is what keeps this from swallowing a deliberate
        rotation re-fetch, which is a real bug this shape had and a test caught:
        an entry fetched microseconds ago is recent, but "recent" is not the
        question — "did somebody else already do my work" is.
        """
        lock = self._locks.setdefault(issuer, asyncio.Lock())
        async with lock:
            current = self._cache.get(issuer)
            if current is not None and current is not stale:
                return current
            keys = await self._fetch(issuer)
            now = time.monotonic()
            entry = _CachedJwks(keys, expires_at=now + self._ttl_s, fetched_at=now)
            self._cache[issuer] = entry
            logger.info("oidc.jwks_refreshed", issuer=issuer, keys=len(keys.keys))
            return entry

    async def _fetch(self, issuer: str) -> PyJWKSet:
        jwks_uri = await self._discover(issuer)
        try:
            response = await self._client.get(jwks_uri, timeout=self._timeout_s)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise denied(f"JWKS fetch failed for {issuer}: {exc!r}") from exc
        try:
            return PyJWKSet.from_dict(document)
        except jwt.PyJWKSetError as exc:
            raise denied(f"malformed JWKS at {jwks_uri}: {exc!r}") from exc

    async def _discover(self, issuer: str) -> str:
        try:
            response = await self._client.get(issuer + DISCOVERY_PATH, timeout=self._timeout_s)
            response.raise_for_status()
            jwks_uri = response.json().get("jwks_uri")
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise denied(f"OIDC discovery failed for {issuer}: {exc!r}") from exc
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise denied(f"OIDC discovery for {issuer} named no jwks_uri")
        # The discovery document is fetched from the IdP but is still remote
        # input. Constraining `jwks_uri` to the issuer's own prefix keeps a
        # compromised or misconfigured document from pointing key retrieval at a
        # host of its choosing — an SSRF with a signing key at the end of it.
        if not jwks_uri.startswith(issuer + "/"):
            raise denied(f"jwks_uri {jwks_uri!r} is outside issuer {issuer}")
        return jwks_uri


@dataclass(frozen=True, slots=True)
class OidcConfig:
    """Everything the validator trusts, all of it from configuration.

    ``issuer_internal`` is where JWKS is fetched; ``trusted_issuers`` is what a
    token's ``iss`` is allowed to equal. They differ under split horizon and that
    is the whole point of keeping them separate fields.
    """

    issuer_internal: str
    trusted_issuers: frozenset[str]
    client_id: str

    @classmethod
    def build(
        cls, *, issuer_internal: str, issuer_public: str | None, client_id: str
    ) -> OidcConfig:
        internal = _normalize_issuer(issuer_internal)
        trusted = {internal}
        if issuer_public:
            trusted.add(_normalize_issuer(issuer_public))
        return cls(
            issuer_internal=internal,
            trusted_issuers=frozenset(trusted),
            client_id=client_id,
        )


class OidcProvider:
    """Validates an OIDC token from the org's configured IdP."""

    def __init__(
        self,
        *,
        provider_id: ProviderId,
        org_id: OrgId,
        config: OidcConfig,
        jwks: JwksSource,
    ) -> None:
        self._provider_id = provider_id
        self._org_id = org_id
        self._config = config
        self._jwks = jwks

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.OIDC

    @property
    def provider_id(self) -> ProviderId:
        return self._provider_id

    async def authenticate(self, *, token: str) -> AuthenticatedSubject:
        header = self._read_header(token)
        key = await self._jwks.key_for(self._config.issuer_internal, header.get("kid"))
        claims = self._decode(token, key)
        self._check_issuer(claims)
        self._check_audience(claims)

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise denied("token carries no usable subject")

        return AuthenticatedSubject(
            org_id=self._org_id,
            provider_id=self._provider_id,
            provider_kind=ProviderKind.OIDC,
            external_subject=subject,
            email=_optional_str(claims, "email"),
            display_name=_optional_str(claims, "name")
            or _optional_str(claims, "preferred_username"),
        )

    @staticmethod
    def _read_header(token: str) -> Mapping[str, Any]:
        """Read the unverified header — for the ``kid`` only.

        This is the one place unverified token data is touched, and it selects a
        *candidate* key. The signature check that follows is what makes the
        selection safe: naming the wrong `kid` gets a verification failure, not a
        bypass. The ``alg`` here is read for the log and never for the decision.
        """
        try:
            return jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise denied(f"unreadable token header: {exc!r}") from exc

    def _decode(self, token: str, key: PyJWK) -> Mapping[str, Any]:
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                leeway=0,
                options={
                    # Replaced below by the aud-or-azp check this IdP needs.
                    "verify_aud": False,
                    "require": list(REQUIRED_CLAIMS),
                    "verify_exp": True,
                    "verify_signature": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise denied("token is expired") from exc
        except jwt.PyJWTError as exc:
            raise denied(f"token failed validation: {exc!r}") from exc
        if not isinstance(claims, dict):
            raise denied("token payload is not a claims object")
        return claims

    def _check_issuer(self, claims: Mapping[str, Any]) -> None:
        issuer = claims.get("iss")
        if not isinstance(issuer, str) or _normalize_issuer(issuer) not in (
            self._config.trusted_issuers
        ):
            raise denied(f"issuer {issuer!r} is not configured for this provider")

    def _check_audience(self, claims: Mapping[str, Any]) -> None:
        """The client id must appear in ``aud`` or in ``azp``. See module docstring."""
        raw_aud = claims.get("aud")
        audiences: Sequence[str]
        if isinstance(raw_aud, str):
            audiences = (raw_aud,)
        elif isinstance(raw_aud, list):
            audiences = [a for a in raw_aud if isinstance(a, str)]
        else:
            audiences = ()
        if self._config.client_id in audiences:
            return
        if claims.get("azp") == self._config.client_id:
            return
        raise denied(f"token was not issued to client {self._config.client_id!r}")


def _optional_str(claims: Mapping[str, Any], name: str) -> str | None:
    value = claims.get(name)
    return value if isinstance(value, str) and value else None
