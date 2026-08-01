"""The authentication strategy seam: what a provider is, and what it returns.

**Two protocols, not one.** Internal auth is handed a secret the caller *knows*
and checks it against a stored hash. OIDC is handed a token another system
*minted* and checks a signature, an issuer and an audience. Forcing those into one
``authenticate(credential)`` signature buys nothing and costs the type checker's
ability to tell a route that passes a password where a token belongs; the shared
part is the *result*, not the call. This mirrors "2 protocols not 4" in
ADAPTATION §3 — API keys (M3.5) are not an ``identity_provider`` row and get no
protocol here, and SAML is deliberately out of scope.

**What a provider returns is a subject, not a principal and not a token.** The
provider answers exactly one question: *is this credential genuine, and whom does
it name?* Loading roles and tags is a repository read the application layer does,
and minting a platform JWT is M3.4. Keeping both out means a provider can be
tested without a database and swapped without touching authorization.

**Every denial reads the same.** :data:`AUTHENTICATION_FAILED` is the only message
that crosses the API boundary from this layer, whether the org is unknown, the
user does not exist, the password is wrong, or the token is forged. A denial that
distinguishes those is an enumeration oracle (`docs/ThreatModel.md`). The
*diagnostic* reason goes to the log, where it belongs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from mnemos.core.errors import AuthenticationError
from mnemos.core.types import ProviderKind
from mnemos.features.identity.domain import OrgId, ProviderId, UserId

#: The single message this layer is allowed to return to a caller.
AUTHENTICATION_FAILED = "authentication failed"


def denied(reason: str) -> AuthenticationError:
    """Build the one denial this layer raises.

    ``reason`` is the diagnostic truth and is carried in ``details`` for the log;
    the message the client sees is constant. The API error handler renders
    ``message`` and never ``details`` (CodingStandards §4), so the two audiences
    stay separated by construction rather than by everyone remembering to.
    """
    return AuthenticationError(AUTHENTICATION_FAILED, reason=reason)


@dataclass(frozen=True, slots=True)
class AuthenticatedSubject:
    """A verified answer to "whom does this credential name?".

    Frozen for the same reason ``Principal`` is: this is the input to authority,
    and anything holding a reference could otherwise widen it after the check that
    approved it.

    Exactly which identity field is populated depends on where the identity came
    from, and both are optional because neither is always knowable:

    * **Internal** auth resolved a local ``app_user`` row to verify a password, so
      it always has a ``user_id``.
    * **OIDC** verified a token minted elsewhere. It knows the IdP's ``sub`` and
      not much else; whether a local user exists for that subject — and whether to
      provision one — is a decision for the application layer, which has the
      org-scoped repository and the just-in-time provisioning policy. Putting it
      here would give every provider a database.

    At least one of the two must be set, or the subject names nobody.
    """

    org_id: OrgId
    provider_id: ProviderId
    provider_kind: ProviderKind
    user_id: UserId | None = None
    external_subject: str | None = None
    email: str | None = None
    display_name: str | None = None

    def __post_init__(self) -> None:
        if self.user_id is None and self.external_subject is None:
            msg = "an authenticated subject must carry a local user id or an external subject"
            raise ValueError(msg)


@runtime_checkable
class CredentialAuthProvider(Protocol):
    """Verifies a secret the caller knows. Internal password auth is the only one.

    The org is bound into the strategy at construction, not passed per call: the
    factory has already resolved which tenant this login is against, and a
    provider that could be asked about a different org is a provider that could be
    asked about the wrong one.
    """

    @property
    def kind(self) -> ProviderKind: ...

    @property
    def provider_id(self) -> ProviderId: ...

    async def authenticate(self, *, email: str, password: str) -> AuthenticatedSubject:
        """Return the subject, or raise :func:`denied`. Never returns ``None``."""
        ...


@runtime_checkable
class TokenAuthProvider(Protocol):
    """Validates a token minted by an external IdP. OIDC (Keycloak) is the only one.

    ``authenticate`` takes the raw compact JWS exactly as presented, because
    signature validation must run over the bytes that were signed. Anything that
    parses it first and passes the parts along has already decided what the token
    says before checking whether it says it truthfully.
    """

    @property
    def kind(self) -> ProviderKind: ...

    @property
    def provider_id(self) -> ProviderId: ...

    async def authenticate(self, *, token: str) -> AuthenticatedSubject:
        """Return the subject, or raise :func:`denied`. Never returns ``None``."""
        ...


#: Either strategy. The login endpoint (M3.3) narrows this by which credential the
#: request actually carried, which is why it is a union and not a base class.
AuthProvider = CredentialAuthProvider | TokenAuthProvider
