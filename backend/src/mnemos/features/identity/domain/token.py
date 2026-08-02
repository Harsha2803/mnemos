"""What a Mnemos-issued credential is allowed to say.

Pure, like the rest of ``domain/``: no PyJWT, no SQLAlchemy, no clock. Signing
lives in ``providers/platform.py`` and persistence in ``adapters/``; what is here
is the *contract* those two have to keep, expressed so that breaking it is a
``ValueError`` rather than a review comment.

**An access token carries identity and nothing else.** `APIContract.md` §2 makes
that a rule; :data:`FORBIDDEN_CLAIMS` makes it a check, enforced on the way *out*
(minting) and on the way *in* (verifying). The reason is revocation: a token that
carries ``roles`` keeps working for the rest of its lifetime after the role is
taken away, and fifteen minutes is a long window for someone who was just
demoted. Roles and tags are read from the database per request instead, which
costs a cached lookup and buys immediate revocation.

Enforcing it at verification too is not redundancy for its own sake. It means a
token minted by some *future* code path that helpfully attaches a `scope` claim
is refused by the code that reads it, so the mistake surfaces as a failed login in
CI rather than as a stale grant in production.

**The org travels inside the refresh credential**, as ``<org_slug>.<secret>``
(:class:`RefreshCredential`). `APIContract.md` §1 says tenancy is derived from the
credential and never from a header or a query parameter, and M3.2 settled *why*
it has to be: every table an authenticated caller touches is under row-level
security, so nothing about them is readable until an org is known. A bare secret
identifies nobody — and looking it up across all tenants is exactly the
``BYPASSRLS`` in the request path that the M3 prerequisite removed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from mnemos.features.identity.domain.ids import OrgId, SessionId, UserId

#: Exactly the claims an access token carries. Listed as a tuple because it is
#: also what the verifier passes to PyJWT's ``require``: a claim that is absent
#: is not defaulted, it is a refusal.
ACCESS_TOKEN_CLAIMS: Final[tuple[str, ...]] = ("sub", "org", "sid", "iat", "exp", "iss", "jti")

#: Claim names that would turn an access token into an authorization decision.
#: Broad on purpose — `realm_access`/`resource_access` are Keycloak's shape and
#: `scp` is the Microsoft one, and neither belongs in a token we mint, so a
#: copy-paste from an IdP payload fails loudly instead of quietly granting.
FORBIDDEN_CLAIMS: Final[frozenset[str]] = frozenset(
    {
        "authorities",
        "entitlements",
        "groups",
        "perms",
        "permissions",
        "realm_access",
        "resource_access",
        "role",
        "roles",
        "scope",
        "scp",
        "tags",
    }
)

#: Separator between the tenant half and the secret half of a refresh credential.
#: ``secrets.token_urlsafe`` emits base64url, which contains ``-`` and ``_`` and
#: never ``.``, so splitting on the *last* one is unambiguous even for an org slug
#: that contains a dot.
REFRESH_TOKEN_SEPARATOR: Final = "."

#: 32 bytes = 256 bits from `secrets`. Enough that the hash column can be a plain
#: SHA-256 digest rather than argon2 (see `core.security.digest_token`), because
#: there is no dictionary for a work factor to slow down.
REFRESH_SECRET_BYTES: Final = 32


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """The decoded body of a platform access token.

    Frozen for the reason ``Principal`` is: this is the input to an authorization
    decision, and anything holding a reference to a mutable one could widen it
    after the check that approved it.

    ``session_id`` is the ``session`` row the token was minted against — the same
    row the refresh chain rotates. It is what lets a future revocation check ask
    "is this session still live" without the token having to carry the answer.
    """

    subject: UserId
    org_id: OrgId
    session_id: SessionId
    token_id: UUID
    issuer: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.issuer:
            msg = "an access token must name an issuer"
            raise ValueError(msg)
        for name, moment in (("issued_at", self.issued_at), ("expires_at", self.expires_at)):
            if moment.tzinfo is None:
                # A naive datetime here becomes a wrong `exp` in whatever the
                # server's local zone happens to be, which is an expiry check
                # that is hours off in one direction or the other.
                msg = f"{name} must be timezone-aware"
                raise ValueError(msg)
        if self.expires_at <= self.issued_at:
            msg = "an access token must expire after it was issued"
            raise ValueError(msg)

    def to_claims(self) -> dict[str, str | int]:
        """The JWT payload. Timestamps are integer epoch seconds, per RFC 7519."""
        return {
            "sub": str(self.subject),
            "org": str(self.org_id),
            "sid": str(self.session_id),
            "jti": str(self.token_id),
            "iss": self.issuer,
            "iat": int(self.issued_at.timestamp()),
            "exp": int(self.expires_at.timestamp()),
        }

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any]) -> AccessTokenClaims:
        """Parse a verified payload, refusing anything that carries authority.

        Raises:
            ValueError: if an authorization claim is present, a required claim is
                missing, or a value is not the type it must be. The caller
                translates that into the one denial the identity layer emits —
                this layer does not know what an HTTP response looks like.
        """
        carried = sorted(FORBIDDEN_CLAIMS & set(claims))
        if carried:
            msg = f"an access token must carry no authorization claims, found {carried}"
            raise ValueError(msg)
        missing = [name for name in ACCESS_TOKEN_CLAIMS if claims.get(name) is None]
        if missing:
            msg = f"access token is missing required claims {missing}"
            raise ValueError(msg)

        issuer = claims["iss"]
        if not isinstance(issuer, str) or not issuer:
            msg = "access token `iss` is not a string"
            raise ValueError(msg)
        return cls(
            subject=UserId(_uuid(claims, "sub")),
            org_id=OrgId(_uuid(claims, "org")),
            session_id=SessionId(_uuid(claims, "sid")),
            token_id=_uuid(claims, "jti"),
            issuer=issuer,
            issued_at=_moment(claims, "iat"),
            expires_at=_moment(claims, "exp"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class RefreshCredential:
    """``<org_slug>.<secret>`` — a refresh token as it travels.

    ``repr=False`` deliberately: the generated dataclass repr would print a live
    bearer secret into any log line, exception message or debugger frame that
    formats the object, and "we never log this" is not a property that survives
    the twentieth call site.

    The slug half is not decoration and not a hint. It is hashed *together with*
    the secret (see :meth:`render`), so the stored digest binds the secret to one
    tenant: presenting the same secret under another org's slug produces a
    different digest and matches no row, on top of the org-scoped read that RLS is
    enforcing underneath.
    """

    org_slug: str
    secret: str

    def __post_init__(self) -> None:
        if not self.org_slug or not self.secret:
            msg = "a refresh credential needs both an org slug and a secret"
            raise ValueError(msg)

    def render(self) -> str:
        """The wire form. A method rather than ``__str__`` so that handing the
        secret to something takes a deliberate call that greps."""
        return f"{self.org_slug}{REFRESH_TOKEN_SEPARATOR}{self.secret}"

    @classmethod
    def parse(cls, presented: str) -> RefreshCredential:
        """Split a presented credential, or raise ``ValueError``.

        Splits on the **last** separator: the secret is base64url and can never
        contain one, while an org slug conceivably can.
        """
        org_slug, separator, secret = presented.rpartition(REFRESH_TOKEN_SEPARATOR)
        if not separator:
            msg = "a refresh credential must be <org_slug>.<secret>"
            raise ValueError(msg)
        return cls(org_slug=org_slug, secret=secret)


@dataclass(frozen=True, slots=True, repr=False)
class TokenPair:
    """What a successful login or rotation produces.

    ``repr=False`` for the same reason :class:`RefreshCredential` has it: this
    object holds both live credentials.

    ``refresh_token`` is rendered rather than structured because the only thing
    the caller does with it is set a cookie. Which cookie, with which flags, is an
    entrypoint concern and is not decided here.
    """

    access_token: str
    expires_in_s: int
    refresh_token: str
    refresh_expires_at: datetime
    org_slug: str
    session_id: SessionId


def _uuid(claims: Mapping[str, Any], name: str) -> UUID:
    value = claims[name]
    if not isinstance(value, str):
        msg = f"access token claim {name!r} is not a string"
        raise ValueError(msg)
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"access token claim {name!r} is not a uuid"
        raise ValueError(msg) from exc


def _moment(claims: Mapping[str, Any], name: str) -> datetime:
    value = claims[name]
    # `bool` is an `int` in Python, and `True` would otherwise become 1970.
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"access token claim {name!r} is not an epoch timestamp"
        raise ValueError(msg)
    return datetime.fromtimestamp(value, tz=UTC)
