"""Platform access tokens: minting and verifying the ones **we** issue.

Deliberately next to ``oidc.py``, because the pair is the point. ``oidc.py``
verifies a token another system minted and we can only check; this verifies a
token we minted and could equally have forged ourselves. The two have opposite
key material and *identical* discipline about the header:

**The algorithm never comes from the token.** :data:`ALLOWED_PLATFORM_ALGORITHMS` is a
one-element tuple passed to the decoder. Reading ``alg`` out of the thing being
verified is the ``alg: none`` forgery — a token with no signature at all, which
verifies against any validator polite enough to do what the header asks. The
same allow-list also refuses HS512 and RS256 under our secret, so nobody can
substitute an algorithm and land in a different code path.

**HS256, and `docs/ThreatModel.md` §5.1 argues it.** In summary: api, worker and
realtime are one trust domain reading one secret, so an asymmetric algorithm
would buy a separation that does not exist, at the cost of a key-management story
this stack has nowhere to put. :class:`PlatformTokenConfig` keeps the algorithm as
a validated field rather than a constant so that the day a verifier appears
outside the signing domain, the change is this allow-list and a key pair.

**The token says who, never what.** The payload is built from
:class:`~mnemos.features.identity.domain.token.AccessTokenClaims`, which refuses
authorization claims in both directions. See its docstring for why roles in a
token are a revocation hole rather than a performance win.

**Every denial reads the same**, through :func:`~.base.denied` — the constant
message to the caller, the diagnostic reason to the log. An expired token and a
forged one are the same answer here for the same reason a wrong password and an
unknown user are.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

import jwt

from mnemos.core.clock import Clock
from mnemos.core.errors import ConfigurationError
from mnemos.core.ids import IdGenerator
from mnemos.features.identity.domain import (
    ACCESS_TOKEN_CLAIMS,
    AccessTokenClaims,
    OrgId,
    SessionId,
    UserId,
)
from mnemos.features.identity.providers.base import denied

#: Symmetric, and exactly one entry. Passed to the decoder; never derived from a
#: token header. Widening this tuple is the change that makes an algorithm
#: substitution possible, so it is a constant rather than configuration.
ALLOWED_PLATFORM_ALGORITHMS: Final[tuple[str, ...]] = ("HS256",)

#: RFC 7518 §3.2: an HMAC key should be at least as long as the hash output.
MIN_SECRET_LENGTH: Final = 32


@dataclass(frozen=True, slots=True, repr=False)
class PlatformTokenConfig:
    """Everything the codec trusts. ``repr=False`` — it holds the signing secret.

    Validated at construction, at the composition root, so a bad secret is a
    process that will not start rather than a login that fails at 3am
    (CodingStandards §7).
    """

    secret: str
    issuer: str
    algorithm: str = ALLOWED_PLATFORM_ALGORITHMS[0]
    access_ttl_s: int = 900
    min_secret_length: int = MIN_SECRET_LENGTH

    def __post_init__(self) -> None:
        if self.algorithm not in ALLOWED_PLATFORM_ALGORITHMS:
            raise ConfigurationError(
                "jwt_algorithm is not an algorithm this system will sign or verify with",
                configured=self.algorithm,
                allowed=list(ALLOWED_PLATFORM_ALGORITHMS),
            )
        if len(self.secret) < self.min_secret_length:
            # Length rather than the secret itself in `details`: this error is
            # logged, and the whole point of the check is that the value is
            # sensitive even when it is bad.
            raise ConfigurationError(
                "jwt_secret is shorter than an HMAC-SHA256 key should be",
                length=len(self.secret),
                minimum=self.min_secret_length,
            )
        if not self.issuer:
            raise ConfigurationError("jwt_issuer must be set")
        if self.access_ttl_s <= 0:
            raise ConfigurationError("access_token_ttl_s must be positive", ttl_s=self.access_ttl_s)


class PlatformTokenCodec:
    """Mints and verifies platform access tokens.

    The clock and the id generator are injected rather than reached for
    (CodingStandards §5): `exp` arithmetic and `jti` uniqueness are the two things
    these tests need to control, and a module that calls ``datetime.now()``
    directly cannot be tested for expiry without sleeping.
    """

    def __init__(
        self,
        *,
        config: PlatformTokenConfig,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._config = config
        self._clock = clock
        self._ids = ids

    @property
    def access_ttl_s(self) -> int:
        return self._config.access_ttl_s

    def mint(
        self, *, subject: UserId, org_id: OrgId, session_id: SessionId
    ) -> tuple[str, AccessTokenClaims]:
        """Sign an access token naming a user, an org and a session.

        Returns both the compact JWS and the claims that went into it, so a
        caller that needs `exp` does not have to decode its own token back — and
        so the two can never disagree.
        """
        now = self._clock.now()
        claims = AccessTokenClaims(
            subject=subject,
            org_id=org_id,
            session_id=session_id,
            token_id=self._ids.new(),
            issuer=self._config.issuer,
            issued_at=now,
            expires_at=now + timedelta(seconds=self._config.access_ttl_s),
        )
        token = jwt.encode(
            claims.to_claims(),
            self._config.secret,
            algorithm=self._config.algorithm,
        )
        return token, claims

    def verify(self, token: str) -> AccessTokenClaims:
        """Check a presented access token, or raise the standard denial.

        **Expiry is checked against the injected clock, not PyJWT's.** PyJWT's
        own `exp`/`iat`/`nbf` verification calls ``datetime.now(UTC)`` internally,
        which silently defeats the `Clock` port that CodingStandards §5 exists to
        provide — a token's lifetime then cannot be tested without sleeping, so in
        practice it does not get tested at the boundaries where it matters. Its
        time options are therefore turned *off* and replaced, exactly as
        ``oidc.py`` turns off ``verify_aud`` and replaces it, rather than left on
        and worked around.

        What PyJWT keeps doing is the part it should: the signature, the fixed
        algorithm allow-list, `iss`, and — through ``require`` — refusing a token
        that carries no `exp` at all. Without that last one, "expiry is checked
        below" would be true and useless, because there would be nothing to check.

        Zero leeway. Clock skew inside a single trust domain is a deployment
        problem, and expiry is the *only* thing a fifteen-minute bearer token has
        going for it; buying thirty seconds of it back to paper over an unsynced
        clock is a bad trade.
        """
        try:
            payload = jwt.decode(
                token,
                self._config.secret,
                algorithms=list(ALLOWED_PLATFORM_ALGORITHMS),
                leeway=0,
                issuer=self._config.issuer,
                options={
                    # No audience on a platform token: the audience *is* this
                    # deployment, and `iss` already says so.
                    "verify_aud": False,
                    "verify_iss": True,
                    "verify_signature": True,
                    # Replaced below, against the injected clock.
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    # PyJWT does not verify a claim it cannot find, so an absent
                    # `exp` would otherwise be an immortal token.
                    "require": list(ACCESS_TOKEN_CLAIMS),
                },
            )
        except jwt.PyJWTError as exc:
            raise denied(f"access token failed validation: {exc!r}") from exc

        if not isinstance(payload, dict):
            raise denied("access token payload is not a claims object")
        try:
            claims = AccessTokenClaims.from_claims(payload)
        except ValueError as exc:
            raise denied(f"access token claims are unusable: {exc}") from exc

        if claims.expires_at <= self._clock.now():
            raise denied("access token is expired")
        return claims
