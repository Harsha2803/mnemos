"""The OIDC authorization-code flow, orchestrated.

M3.2 built a validator; nothing yet *obtained* a token for it to validate. This is
the round trip: send the browser to the IdP, take back a code, exchange it
server-side, and hand the resulting ID token to the validator that already knows
how to refuse a forged one.

It lives in ``application`` rather than ``providers`` because it is a use case,
not a strategy — it composes a provider, a discovery cache and a state store, and
knows nothing about HTTP routing (that is ``entrypoints/api``). Layering rule:
``domain ← application ← adapters/api``.

**Split horizon, concretely.** Discovery runs over ``issuer_internal`` because the
API is inside the compose network and ``localhost:8080`` may be someone else's
machine. The browser is redirected to ``issuer_public`` because ``keycloak:8080``
does not resolve in a browser. The code exchange runs server-to-server over
``issuer_internal`` again. Getting any one of those backwards is the classic
containerised-OIDC failure, and each is a separate line below for that reason.

**Three controls, none of them optional:**

*PKCE.* ``mnemos-web`` is a public client, so it has no secret. Without PKCE, an
authorization code intercepted on the redirect is redeemable by anybody. The
verifier never leaves this process; only its SHA-256 goes to the IdP.

*``state``, verified on return.* Without it the callback accepts any code anyone
sends it, which logs a victim into an attacker's account — a login CSRF.

*``state`` is single-use.* It is deleted as it is read
(:meth:`LoginStateStore.take`), so a replayed callback finds nothing. Storing it
in Redis rather than in process memory is what makes that true across two API
replicas and across a restart; an in-memory dict would silently degrade to "works
on my single container".
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

from mnemos.core.logging import get_logger
from mnemos.features.identity.providers import (
    AuthenticatedSubject,
    MetadataSource,
    OidcProvider,
    ProviderFactory,
    denied,
    public_authorization_endpoint,
)

logger = get_logger(__name__)

#: RFC 7636 allows 43-128 characters. 64 random bytes, base64url-encoded, sits
#: near the top of that range.
_VERIFIER_BYTES = 64
_STATE_BYTES = 32

#: How long a half-finished login may sit in Redis. Long enough for a human to
#: type a password and clear MFA, short enough that an abandoned attempt is not a
#: standing credential.
DEFAULT_STATE_TTL_S = 600

TOKEN_EXCHANGE_TIMEOUT_S = 10.0

#: `openid` is what makes this OIDC rather than bare OAuth2 — without it there is
#: no ID token to validate.
DEFAULT_SCOPES = "openid profile email"


@dataclass(frozen=True, slots=True)
class LoginState:
    """What the callback needs to remember from before the redirect.

    The org is carried here rather than trusted from the callback's query string:
    a returning request that names its own tenant would let an attacker swap the
    org between `authorize` and `callback` and have the code validated against a
    different provider's configuration.
    """

    org_slug: str
    provider_slug: str
    code_verifier: str
    redirect_uri: str


class LoginStateStore(Protocol):
    async def put(self, state: str, value: LoginState, *, ttl_s: int) -> None: ...

    async def take(self, state: str) -> LoginState | None:
        """Read **and delete**, atomically. A second call for the same state must
        return ``None`` — that is what makes a replayed callback a denial."""
        ...


@dataclass(frozen=True, slots=True)
class AuthorizationRedirect:
    url: str
    state: str


@dataclass(frozen=True, slots=True)
class CompletedLogin:
    """The verified subject, plus the org slug the login was against.

    The slug is here because ``AuthenticatedSubject`` carries the org *id* — the
    thing the rest of the system authorizes with — while the caller asked in
    slugs and gets an answer in the terms it asked. It comes from the stored
    state, never from the callback's query string.
    """

    subject: AuthenticatedSubject
    org_slug: str
    provider_slug: str


class OidcLoginFlow:
    """Begins and completes the authorization-code + PKCE round trip."""

    def __init__(
        self,
        *,
        factory: ProviderFactory,
        metadata: MetadataSource,
        states: LoginStateStore,
        client: httpx.AsyncClient,
        state_ttl_s: int = DEFAULT_STATE_TTL_S,
        timeout_s: float = TOKEN_EXCHANGE_TIMEOUT_S,
    ) -> None:
        self._factory = factory
        self._metadata = metadata
        self._states = states
        self._client = client
        self._state_ttl_s = state_ttl_s
        self._timeout_s = timeout_s

    async def begin(
        self, *, org_slug: str, provider_slug: str | None, redirect_uri: str
    ) -> AuthorizationRedirect:
        provider = await self._oidc_provider(org_slug, provider_slug)
        config = provider.config
        metadata = await self._metadata.metadata_for(config.issuer_internal)

        verifier = secrets.token_urlsafe(_VERIFIER_BYTES)
        state = secrets.token_urlsafe(_STATE_BYTES)
        await self._states.put(
            state,
            LoginState(
                org_slug=org_slug,
                # Resolved, not echoed: `provider_slug` may have been None and
                # defaulted, and the callback must rebuild the *same* strategy.
                provider_slug=provider_slug or "",
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            ),
            ttl_s=self._state_ttl_s,
        )

        query = urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": redirect_uri,
                "scope": DEFAULT_SCOPES,
                "state": state,
                "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        url = f"{public_authorization_endpoint(metadata, config.issuer_public)}?{query}"
        logger.info("oidc.authorize_begin", org=org_slug, issuer=config.issuer_public)
        return AuthorizationRedirect(url=url, state=state)

    async def complete(self, *, state: str, code: str) -> CompletedLogin:
        stored = await self._states.take(state)
        if stored is None:
            # Unknown, expired, or already used. All three are the same answer:
            # distinguishing them tells an attacker whether a guessed state was
            # ever real.
            raise denied("callback presented an unknown, expired or replayed state")

        provider = await self._oidc_provider(stored.org_slug, stored.provider_slug or None)
        config = provider.config
        metadata = await self._metadata.metadata_for(config.issuer_internal)
        id_token = await self._exchange(metadata.token_endpoint, code, stored, config.client_id)

        # The token came straight from the IdP over a server-to-server call, and
        # it is still validated in full. "We fetched it ourselves" is not a
        # signature check: it proves the transport, not the contents, and the
        # audience check in particular is what stops a token minted for another
        # client in the same realm.
        subject = await provider.authenticate(token=id_token)
        logger.info(
            "oidc.authorize_complete", org=stored.org_slug, subject=subject.external_subject
        )
        return CompletedLogin(
            subject=subject,
            org_slug=stored.org_slug,
            provider_slug=stored.provider_slug or "",
        )

    async def _oidc_provider(self, org_slug: str, provider_slug: str | None) -> OidcProvider:
        provider = await self._factory.for_org(org_slug, provider_slug)
        if not isinstance(provider, OidcProvider):
            # An internal-password provider reached through the OIDC endpoints is
            # a misrouted request, not a fallback to try.
            raise denied(f"provider for org {org_slug!r} is not an OIDC provider")
        return provider

    async def _exchange(
        self, token_endpoint: str, code: str, stored: LoginState, client_id: str
    ) -> str:
        try:
            response = await self._client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    # Must match the value sent at `authorize` byte for byte —
                    # the IdP checks it, and it is why the redirect URI is
                    # stored rather than recomputed from the callback request.
                    "redirect_uri": stored.redirect_uri,
                    "client_id": client_id,
                    "code_verifier": stored.code_verifier,
                },
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as exc:
            raise denied(f"token exchange failed: {exc!r}") from exc

        if response.status_code != httpx.codes.OK:
            # The IdP's error body is diagnostic and goes to the log only; it can
            # name the client and the grant, which the caller does not get to see.
            raise denied(f"token endpoint returned {response.status_code}: {response.text[:200]}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise denied("token endpoint returned a non-JSON body") from exc

        id_token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(id_token, str) or not id_token:
            # No `id_token` means the `openid` scope was dropped or the client is
            # configured for bare OAuth2. Falling back to the access token would
            # authenticate against a token that carries no identity contract.
            raise denied("token response carried no id_token")
        return id_token


def _challenge(verifier: str) -> str:
    """S256: base64url(SHA-256(verifier)), unpadded, per RFC 7636 §4.2."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
