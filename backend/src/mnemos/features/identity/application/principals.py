"""Turning a presented access token into a :class:`Principal`.

``application/tokens.py`` mints the credential; this is the other direction —
what happens on every authenticated request afterwards. It is the step M3.1's
``Principal`` was written for and that nothing produced until now.

**Roles and tags are read from the repository, never from the token.**
`domain/token.py` refuses authorization claims when minting *and* when verifying,
and `test_access_token_carries_no_roles_or_permissions` pins the wire bytes. That
discipline is only worth something if the reader honours it: a guard that took
``roles`` out of a token would keep granting a revoked role for the rest of the
token's fifteen minutes, and fifteen minutes is a long time for somebody who was
just demoted. So the token answers exactly two questions — *is this signature
ours* and *whom does it name* — and the answer to *what may they do* is a
database read, per request, every request. The cost is a cached lookup; the
benefit is that revocation takes effect on the next call.

**The session is checked for liveness, and that is what makes sign-out real.**
`AccessTokenClaims` carries ``sid`` precisely so this question can be asked
without the token having to carry the answer. Without the check, signing out
would revoke the refresh family and leave the access token working until it
expired — a "sign out" that leaves the door open for fifteen minutes is not one.
A *rotated* predecessor stays live here on purpose: rotation retires a refresh
token, it does not end the session.

**Every denial reads the same**, through :func:`~..providers.base.denied`: an
expired token, a forged one, a deactivated user and a revoked session are one
answer to the caller and four different lines in the log.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mnemos.core.clock import Clock
from mnemos.core.logging import get_logger
from mnemos.features.identity.domain import (
    OrgId,
    PermissionSet,
    Principal,
    PrincipalKind,
    SessionId,
    TagSet,
    UserId,
)
from mnemos.features.identity.providers import PlatformTokenCodec, denied

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UserAuthority:
    """Everything a request needs to know about the caller, read live.

    A flat value object rather than an ORM row, for the reason
    ``providers/ports.py`` gives: an ``AppUser`` escaping the adapter carries a
    live session, and a lazy load fired from inside an authorization decision
    surfaces as a ``MissingGreenlet`` a long way from its cause.

    ``permissions`` are the raw ``resource:action`` strings as stored in
    ``role.permissions``. Parsing them is
    :meth:`~mnemos.features.identity.domain.permission.PermissionSet.parse`'s
    job and it is deliberately tolerant — one malformed grant in a role's JSONB
    must not be able to break authorization for the whole principal.
    """

    user_id: UserId
    org_id: OrgId
    org_slug: str
    email: str
    display_name: str
    is_active: bool
    permissions: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthenticatedCaller:
    """A resolved request identity: the principal, plus how to name it on screen.

    ``Principal`` carries an ``org_id`` and no slug, and it should stay that way
    — it is the object authorization is decided against, and a display string has
    no business in it. The sidebar still has to say *which* tenant somebody is
    signed in to, so the human-readable half rides alongside rather than inside.
    """

    principal: Principal
    email: str
    display_name: str
    org_slug: str


class PrincipalRepository(Protocol):
    """The per-request authority read, narrowed to two questions.

    Both take ``org_id`` explicitly. That is not redundancy with row-level
    security — it is CodingStandards §6: the explicit predicate is what lets the
    planner use the composite index, and RLS is the layer that catches what
    review misses.
    """

    async def load_authority(self, org_id: OrgId, user_id: UserId) -> UserAuthority | None:
        """The caller's roles, tags and status **now**, not when they signed in."""
        ...

    async def session_is_live(self, org_id: OrgId, session_id: SessionId, at: datetime) -> bool:
        """Whether the ``session`` row the token names is neither revoked nor expired."""
        ...


class PrincipalResolver:
    """Access token in, :class:`Principal` out, or the one denial."""

    def __init__(
        self,
        *,
        codec: PlatformTokenCodec,
        repository: PrincipalRepository,
        clock: Clock,
    ) -> None:
        self._codec = codec
        self._repository = repository
        self._clock = clock

    async def resolve(self, access_token: str) -> AuthenticatedCaller:
        """Verify the token, then hydrate authority from the database.

        The order matters. Verification is a signature check with no I/O, so an
        unauthenticated flood costs an HMAC rather than two round trips to
        Postgres; and nothing reaches the database on behalf of a token that
        was never ours.
        """
        claims = self._codec.verify(access_token)

        authority = await self._repository.load_authority(claims.org_id, claims.subject)
        if authority is None:
            raise denied(f"access token names user {claims.subject} which no longer exists")
        if not authority.is_active:
            raise denied(f"user {claims.subject} is deactivated")

        if not await self._repository.session_is_live(
            claims.org_id, claims.session_id, self._clock.now()
        ):
            raise denied(f"session {claims.session_id} is revoked or expired")

        principal = Principal(
            org_id=authority.org_id,
            principal_id=authority.user_id,
            kind=PrincipalKind.USER,
            permissions=PermissionSet.parse(authority.permissions),
            tags=TagSet.from_iterable(authority.tags),
            session_id=claims.session_id,
        )
        logger.debug(
            "identity.principal_resolved",
            org_id=str(principal.org_id),
            user_id=str(principal.principal_id),
            session_id=str(claims.session_id),
            permissions=len(principal.permissions),
        )
        return AuthenticatedCaller(
            principal=principal,
            email=authority.email,
            display_name=authority.display_name,
            org_slug=authority.org_slug,
        )


def flatten_grants(grant_lists: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """Every grant from every bound role, de-duplicated, order-stable.

    Here rather than in the adapter because it is a rule about the *model* —
    bindings are additive and a permission held twice is held once — and because
    a future non-SQL repository must flatten them the same way.
    """
    seen: dict[str, None] = {}
    for grants in grant_lists:
        for grant in grants:
            if isinstance(grant, str):
                seen.setdefault(grant, None)
    return tuple(seen)
