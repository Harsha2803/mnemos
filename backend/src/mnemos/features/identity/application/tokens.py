"""Issuing, rotating and revoking the credential pair a signed-in user holds.

M3.3 ended at a verified subject: proof that a login *happened*, with no way to
stay logged in. This is the other half — a 15-minute access token plus a
long-lived refresh token, and the machinery that makes the long-lived half safe
to hold.

**Rotation, and why the family dies.** Every use of a refresh token issues a new
one and records the successor on the old row (`session.rotated_to`). Presenting a
token whose row *already* names a successor is therefore proof of theft rather
than a suspicion: the legitimate holder and the thief cannot both be holding the
current token, so one of the two is replaying a copy — and which one is
unknowable from here. The only safe answer is to revoke the entire chain and make
both parties log in again. A system that merely refused the stale token would
leave the thief holding the live one.

That includes losing the compare-and-set race in :meth:`TokenService.refresh`.
Two requests presenting the same token concurrently is the same evidence as
presenting a rotated one; it just arrives through a different door. The frontend
consequence is real and is written down in TRACKER §5 M3.4 item 8: a client that
fires N requests, gets N 401s and refreshes N times revokes its own session.

**The org travels in the credential**, as ``<org_slug>.<secret>``, settled in
M3.2. Everything an authenticated caller touches is under row-level security, so
a bare secret identifies nobody and looking one up across all tenants is the
``BYPASSRLS`` in the request path that the M3 prerequisite removed. The slug is
hashed *together with* the secret, so the digest binds the secret to one tenant
on top of the org-scoped read.

**Just-in-time provisioning, decided here.** See :meth:`TokenService._resolve_user`.

**What this layer does not do.** It loads no roles, no tags and no permissions.
Those are a per-request read against the live database (`APIContract.md` §2), and
keeping them out of both the token and the session row is what makes revoking a
role take effect on the next request rather than in fifteen minutes.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from mnemos.core.clock import Clock
from mnemos.core.errors import AuthenticationError
from mnemos.core.logging import get_logger
from mnemos.core.security import digest_token, tokens_equal
from mnemos.features.identity.domain import (
    REFRESH_SECRET_BYTES,
    OrgId,
    ProviderId,
    RefreshCredential,
    SessionId,
    TokenPair,
    UserId,
)
from mnemos.features.identity.providers import (
    AuthenticatedSubject,
    OrgDirectory,
    OrgRecord,
    PlatformTokenCodec,
    denied,
)
from mnemos.features.observability.application.ports import AuditRepository
from mnemos.features.observability.domain import Outcome

logger = get_logger(__name__)

#: Written to `session.revoked_reason`. Stable strings, because they are what an
#: operator greps for when a user reports being logged out — and because
#: "reuse detected" is the one worth an alert.
REVOKED_BY_REUSE = "refresh_token_reuse_detected"
REVOKED_BY_SIGN_OUT = "signed_out"


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One ``session`` row, as this layer reads it.

    A flat value object rather than the ORM row, for the reason
    ``providers/ports.py`` gives: an ORM object escaping the adapter carries a
    live session with it, and a lazy load fired from inside an authentication
    decision surfaces as a `MissingGreenlet` far from its cause.

    ``refresh_token_hash`` is here even though the lookup was *by* that hash, so
    the application can confirm the match with
    :func:`~mnemos.core.security.tokens_equal` rather than trusting the SQL
    ``=`` that found it. Cheap, and it keeps the comparison in the layer that
    knows it is comparing a secret's digest.
    """

    session_id: SessionId
    org_id: OrgId
    user_id: UserId
    refresh_token_hash: str
    rotated_to: SessionId | None
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class AppUserRecord:
    """The identity half of an ``app_user`` row. No password hash: this layer
    never verifies a secret, it only decides who a verified subject *is*."""

    user_id: UserId
    org_id: OrgId
    email: str
    display_name: str
    external_subject: str | None
    is_active: bool


class SessionStore(Protocol):
    """The ``session`` table, narrowed to what rotation needs.

    Every method takes ``org_id`` explicitly. That is not redundancy with RLS —
    it is CodingStandards §6: the explicit filter lets the planner use the
    composite index, and RLS catches what review misses.
    """

    async def find_by_token_hash(self, org_id: OrgId, token_hash: str) -> SessionRecord | None: ...

    async def open(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> SessionId: ...

    async def rotate(
        self,
        *,
        org_id: OrgId,
        predecessor: SessionId,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> SessionId | None:
        """Insert the successor and claim the predecessor, atomically.

        Returns ``None`` when the predecessor was **already** rotated or revoked
        by the time the update ran — a compare-and-set, not a read-then-write.
        The caller treats that as reuse. Without the conditional update, two
        concurrent presentations of one token would both read ``rotated_to IS
        NULL``, both succeed, and produce two live chains from one credential,
        which is the exact state the family kill exists to make impossible.
        """
        ...

    async def revoke_family(
        self, *, org_id: OrgId, member: SessionId, reason: str, at: datetime
    ) -> Sequence[SessionId]:
        """Revoke every session reachable from ``member`` along ``rotated_to``,
        in both directions, and return what was revoked."""
        ...


class AppUserStore(Protocol):
    """``app_user``, for mapping a verified subject onto a local row."""

    async def find_by_id(self, org_id: OrgId, user_id: UserId) -> AppUserRecord | None: ...

    async def find_by_external_subject(
        self, org_id: OrgId, external_subject: str
    ) -> AppUserRecord | None: ...

    async def find_by_email(self, org_id: OrgId, email: str) -> AppUserRecord | None: ...

    async def create(
        self,
        *,
        org_id: OrgId,
        provider_id: ProviderId,
        external_subject: str,
        email: str,
        display_name: str,
    ) -> AppUserRecord: ...

    async def record_login(self, org_id: OrgId, user_id: UserId, at: datetime) -> None: ...


class TokenService:
    """Issues the pair, rotates it, and kills a stolen family."""

    def __init__(
        self,
        *,
        orgs: OrgDirectory,
        users: AppUserStore,
        sessions: SessionStore,
        codec: PlatformTokenCodec,
        clock: Clock,
        refresh_ttl_s: int,
        audit: AuditRepository | None = None,
    ) -> None:
        self._orgs = orgs
        self._users = users
        self._sessions = sessions
        self._codec = codec
        self._clock = clock
        self._refresh_ttl_s = refresh_ttl_s
        # Optional so every existing test construction of this service keeps
        # working unchanged; `None` just means sign-in/sign-out events are not
        # recorded, which is also what a unit test that fakes the other four
        # collaborators should get for free (TRACKER §5 deliverable 5).
        self._audit = audit

    async def issue_for_subject(
        self,
        *,
        subject: AuthenticatedSubject,
        org_slug: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """Open a session for a subject a provider has already verified.

        ``org_slug`` is re-resolved rather than trusted, and the resulting org id
        is checked against the one the provider bound into the subject. They can
        only differ if a caller composed a subject with a slug from somewhere
        else — which is precisely the confusion this check exists to refuse.
        """
        org = await self._orgs.find_org(org_slug.strip())
        if org is None or not org.is_active:
            # No tenant to attribute this to — `audit_log.org_id` is NOT NULL,
            # so a failure this early cannot become a row in anyone's audit
            # trail. Every failure from here on has a resolved org and is
            # recorded.
            raise denied(f"no active org with slug {org_slug!r}")
        try:
            if org.org_id != subject.org_id:
                raise denied(
                    f"subject belongs to org {subject.org_id} but the login named {org.slug!r}"
                )
            user = await self._resolve_user(subject)
        except AuthenticationError as exc:
            # `exc.details["reason"]` is the diagnostic truth `denied()` carries
            # for the log (`providers/base.py`); `str(exc)`/`exc.message` is the
            # one constant string a caller is allowed to see. An audit row is
            # for the admin reading it afterward, not the caller, so it gets
            # the real reason.
            await self._audit_signin(
                org_id=org.org_id, outcome="deny", reason=exc.details.get("reason", exc.message)
            )
            raise
        now = self._clock.now()
        # The canonical slug from the row, never the one the caller typed: `slug`
        # is CITEXT, so "Acme" and "acme" are the same tenant, and hashing the
        # caller's spelling would mint a credential that only refreshes if the
        # client echoes the same capitalisation back.
        credential = RefreshCredential(org_slug=org.slug, secret=_new_secret())
        expires_at = now + timedelta(seconds=self._refresh_ttl_s)
        session_id = await self._sessions.open(
            org_id=user.org_id,
            user_id=user.user_id,
            token_hash=digest_token(credential.render()),
            issued_at=now,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self._users.record_login(user.org_id, user.user_id, now)
        logger.info(
            "identity.session_opened",
            org_id=str(user.org_id),
            user_id=str(user.user_id),
            session_id=str(session_id),
        )
        await self._audit_signin(org_id=user.org_id, actor_id=user.user_id, outcome="allow")
        return self._pair(credential, org.slug, user, session_id, expires_at)

    async def refresh(
        self,
        presented: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """Exchange a refresh token for a new pair, killing the family on reuse."""
        _, org, row = await self._locate(presented)
        now = self._clock.now()

        if row.revoked_at is not None:
            raise denied(f"session {row.session_id} was revoked at {row.revoked_at.isoformat()}")
        if row.rotated_to is not None:
            # Proof of theft, not a suspicion — see the module docstring.
            await self._kill_family(org.org_id, row.session_id, REVOKED_BY_REUSE, now)
            raise denied(f"refresh token for session {row.session_id} was already rotated")
        if row.expires_at <= now:
            raise denied(f"refresh token for session {row.session_id} expired")

        user = await self._users.find_by_id(org.org_id, row.user_id)
        if user is None or not user.is_active:
            # A deactivated user must not be able to refresh their way through
            # the rest of the fourteen-day window.
            raise denied(f"user {row.user_id} is absent or inactive")

        successor = RefreshCredential(org_slug=org.slug, secret=_new_secret())
        expires_at = now + timedelta(seconds=self._refresh_ttl_s)
        session_id = await self._sessions.rotate(
            org_id=org.org_id,
            predecessor=row.session_id,
            token_hash=digest_token(successor.render()),
            issued_at=now,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        if session_id is None:
            # Somebody rotated this row between the read above and the update.
            # Same evidence, different door.
            await self._kill_family(org.org_id, row.session_id, REVOKED_BY_REUSE, now)
            raise denied(f"concurrent use of the refresh token for session {row.session_id}")

        logger.info(
            "identity.session_rotated",
            org_id=str(org.org_id),
            user_id=str(user.user_id),
            session_id=str(session_id),
            predecessor=str(row.session_id),
        )
        return self._pair(successor, org.slug, user, session_id, expires_at)

    async def revoke(self, presented: str) -> None:
        """Sign out: revoke the whole chain the presented token belongs to.

        **Never raises and never reports what it found.** RFC 7009 §2.2 asks for
        the same, and the reason is that a revocation endpoint which answers 401
        for an unknown token and 204 for a known one is a free oracle for testing
        stolen credentials — from an *unauthenticated* caller, since presenting
        the token is the only authentication it has.

        The whole chain rather than one link: signing out of a device should not
        leave that device's previous refresh token usable, and the chain is
        exactly the set of tokens that device has held.
        """
        try:
            _, org, row = await self._locate(presented)
        except AuthenticationError:
            # Narrow on purpose: a *denial* here is the ordinary outcome of
            # signing out with a token that has already expired or been used,
            # and answering 204 to it is the whole point. An infrastructure
            # failure is not that and must still propagate (CodingStandards §4).
            logger.info("identity.revoke_ignored")
            return
        await self._kill_family(org.org_id, row.session_id, REVOKED_BY_SIGN_OUT, self._clock.now())
        await self._audit_signout(org_id=org.org_id, actor_id=row.user_id)

    # ------------------------------------------------------------------ internals

    async def _audit_signin(
        self,
        *,
        org_id: OrgId,
        outcome: Outcome,
        actor_id: UserId | None = None,
        reason: str | None = None,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            org_id=org_id,
            actor_id=actor_id,
            actor_kind="user",
            action="auth.sign_in",
            resource_kind="session",
            resource_id=None,
            outcome=outcome,
            reason=reason,
        )

    async def _audit_signout(self, *, org_id: OrgId, actor_id: UserId) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            org_id=org_id,
            actor_id=actor_id,
            actor_kind="user",
            action="auth.sign_out",
            resource_kind="session",
            resource_id=None,
            outcome="allow",
        )

    async def _locate(self, presented: str) -> tuple[RefreshCredential, OrgRecord, SessionRecord]:
        """Presented string -> (credential, org, row), or the standard denial."""
        try:
            credential = RefreshCredential.parse(presented.strip())
        except ValueError as exc:
            raise denied(f"malformed refresh credential: {exc}") from exc

        org = await self._orgs.find_org(credential.org_slug)
        if org is None or not org.is_active:
            raise denied(f"no active org with slug {credential.org_slug!r}")

        # Hashed against the *canonical* slug, so the digest is stable across the
        # caller's capitalisation and still binds the secret to this one tenant:
        # the same secret under another org's slug digests differently and
        # matches nothing, underneath an org-scoped read that RLS enforces.
        presented_hash = digest_token(
            RefreshCredential(org_slug=org.slug, secret=credential.secret).render()
        )
        row = await self._sessions.find_by_token_hash(org.org_id, presented_hash)
        if row is None:
            raise denied("no session holds the presented refresh token")
        if not tokens_equal(row.refresh_token_hash, presented_hash):
            # Unreachable through the SQL lookup above, and kept because the
            # lookup is not the only way a row could arrive here.
            raise denied(f"session {row.session_id} hash does not match after lookup")
        return credential, org, row

    async def _kill_family(
        self, org_id: OrgId, member: SessionId, reason: str, at: datetime
    ) -> None:
        revoked = await self._sessions.revoke_family(
            org_id=org_id, member=member, reason=reason, at=at
        )
        logger.warning(
            "identity.session_family_revoked",
            org_id=str(org_id),
            member=str(member),
            reason=reason,
            revoked=len(revoked),
        )

    async def _resolve_user(self, subject: AuthenticatedSubject) -> AppUserRecord:
        """Map a verified subject onto an ``app_user`` row — provisioning if needed.

        **Just-in-time provisioning is on, and deliberately.** By the time this
        runs, the org exists, its `identity_provider` row is enabled, and the IdP
        we configured has authenticated the person. Requiring an administrator to
        pre-create every row would mean nobody but the bootstrap admin (M3.7) can
        ever sign in, which is not a security control so much as a reason to
        share one account.

        **What provisioning grants is identity, never authority.** The new row
        gets no `role_binding` and no `user_tag`, so a just-provisioned user can
        sign in and do nothing at all until M3.6/M3.7 binds a role. Existence is
        not permission, and keeping those separate is what makes the answer to
        "should we auto-provision" safe rather than convenient.

        **Matching is on `external_subject`, never on email.** An IdP email is a
        mutable, frequently-unverified attribute of an account at the IdP; a
        system that links on it lets whoever can set an email there inherit a
        local account. So an email that already belongs to a *different* subject
        is a denial, and linking an IdP identity to a pre-existing local user is
        an administrative action with a human in it — not something an
        unauthenticated login performs on its own behalf.
        """
        if subject.user_id is not None:
            # Internal password auth already resolved a local row to verify
            # against; there is nothing to provision.
            user = await self._users.find_by_id(subject.org_id, subject.user_id)
            if user is None or not user.is_active:
                raise denied(f"user {subject.user_id} is absent or inactive")
            return user

        external = subject.external_subject
        if external is None:  # pragma: no cover - AuthenticatedSubject forbids it
            raise denied("subject names neither a local user nor an external subject")

        existing = await self._users.find_by_external_subject(subject.org_id, external)
        if existing is not None:
            if not existing.is_active:
                raise denied(f"user {existing.user_id} is deactivated")
            return existing

        email = subject.email
        if not email:
            # `app_user.email` is NOT NULL and uniquely indexed per org.
            # Synthesising one from the subject id would produce an
            # unaddressable account that collides the moment the IdP starts
            # asserting a real address, so this is a refusal rather than a guess.
            raise denied(f"IdP asserted no email for subject {external!r}; cannot provision")
        if await self._users.find_by_email(subject.org_id, email) is not None:
            raise denied(f"email {email!r} already belongs to a different subject in this org")

        created = await self._users.create(
            org_id=subject.org_id,
            provider_id=subject.provider_id,
            external_subject=external,
            email=email,
            display_name=subject.display_name or email,
        )
        logger.info(
            "identity.user_provisioned",
            org_id=str(subject.org_id),
            user_id=str(created.user_id),
            provider_id=str(subject.provider_id),
        )
        return created

    def _pair(
        self,
        credential: RefreshCredential,
        org_slug: str,
        user: AppUserRecord,
        session_id: SessionId,
        refresh_expires_at: datetime,
    ) -> TokenPair:
        access_token, claims = self._codec.mint(
            subject=user.user_id, org_id=user.org_id, session_id=session_id
        )
        return TokenPair(
            access_token=access_token,
            expires_in_s=int((claims.expires_at - claims.issued_at).total_seconds()),
            refresh_token=credential.render(),
            refresh_expires_at=refresh_expires_at,
            org_slug=org_slug,
            session_id=session_id,
        )


def _new_secret() -> str:
    """256 bits from `secrets`, never `random` (`docs/ThreatModel.md` §5)."""
    return secrets.token_urlsafe(REFRESH_SECRET_BYTES)
