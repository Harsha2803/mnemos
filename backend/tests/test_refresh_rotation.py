"""M3.4 — refresh-token rotation, the family kill, and JIT provisioning.

Hermetic. What is under test here is the **policy**: when a family dies, what a
deactivated user can still do, which subject maps to which `app_user`, and what
the caller is told about any of it. None of that is a property of Postgres.

What *is* a property of Postgres is the recursive walk that finds a whole chain
from an arbitrary member, and the compare-and-set that makes two concurrent
rotations impossible. The fakes below implement both, so a test that only ran
here would be proving the fake — which is the trap `test_tenant_isolation.py`
exists to avoid. `tests/test_session_store.py` runs the real statements against a
real Postgres, and that is where the SQL is proved.

`test_a_verified_subject_receives_a_working_pair` is the control, first in the
file, for the reason M3.2 recorded next to `test_oidc_provider_accepts_a_genuine
_token`: a service that denies everything passes every revocation test below it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from mnemos.core.clock import FrozenClock
from mnemos.core.errors import AuthenticationError
from mnemos.core.ids import Uuid7Generator
from mnemos.core.security import digest_token
from mnemos.core.types import ProviderKind
from mnemos.features.identity.application.tokens import (
    REVOKED_BY_REUSE,
    REVOKED_BY_SIGN_OUT,
    AppUserRecord,
    SessionRecord,
    TokenService,
)
from mnemos.features.identity.domain import (
    AccessTokenClaims,
    OrgId,
    ProviderId,
    RefreshCredential,
    SessionId,
    UserId,
)
from mnemos.features.identity.providers import (
    AUTHENTICATION_FAILED,
    AuthenticatedSubject,
    OrgRecord,
    PlatformTokenCodec,
    PlatformTokenConfig,
)

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
REFRESH_TTL_S = 60 * 60 * 24 * 14
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

ACME = OrgRecord(org_id=OrgId(uuid4()), slug="acme", is_active=True)
GLOBEX = OrgRecord(org_id=OrgId(uuid4()), slug="globex", is_active=True)
PROVIDER_ID = ProviderId(uuid4())

EXTERNAL_SUBJECT = "9f1c0b2e-keycloak-subject"
EMAIL = "ada@example.test"


# ------------------------------------------------------------------------ fakes


class FakeOrgs:
    """`OrgDirectory`, keyed by slug the way `SqlOrgDirectory` keys it.

    Lookup is case-insensitive because the column is CITEXT; a fake that compared
    case-sensitively would let a test pass against behaviour the database does
    not have.
    """

    def __init__(self, *orgs: OrgRecord) -> None:
        self._orgs = list(orgs)

    async def find_org(self, slug: str) -> OrgRecord | None:
        return next((o for o in self._orgs if o.slug.lower() == slug.lower()), None)

    async def find_provider(self, org_id: OrgId, slug: str) -> None:
        raise AssertionError("the token service must never build a provider")

    async def list_enabled_providers(self, org_id: OrgId) -> Sequence[object]:
        raise AssertionError("the token service must never build a provider")


@dataclass
class _Row:
    """A mutable `session` row. The real one is a table; this is the fake."""

    record: SessionRecord
    revoked_reason: str | None = None


class FakeSessions:
    """In-memory `SessionStore`.

    The two behaviours that matter are reproduced rather than stubbed, because
    the tests below would otherwise be vacuous: `rotate` is a compare-and-set,
    and `revoke_family` walks `rotated_to` in **both** directions. Reproducing
    them here proves nothing about the SQL — see the module docstring — but a
    fake that let a rotated row rotate again would make the family tests pass for
    the wrong reason.
    """

    def __init__(self, ids: Uuid7Generator) -> None:
        self._ids = ids
        self.rows: dict[SessionId, _Row] = {}

    async def find_by_token_hash(self, org_id: OrgId, token_hash: str) -> SessionRecord | None:
        return next(
            (
                r.record
                for r in self.rows.values()
                if r.record.org_id == org_id and r.record.refresh_token_hash == token_hash
            ),
            None,
        )

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
    ) -> SessionId:
        session_id = SessionId(self._ids.new())
        self.rows[session_id] = _Row(
            SessionRecord(
                session_id=session_id,
                org_id=org_id,
                user_id=user_id,
                refresh_token_hash=token_hash,
                rotated_to=None,
                expires_at=expires_at,
                revoked_at=None,
            )
        )
        return session_id

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
        old = self.rows.get(predecessor)
        if old is None or old.record.rotated_to is not None or old.record.revoked_at is not None:
            return None  # the compare-and-set the SQL does in one statement
        successor = await self.open(
            org_id=org_id,
            user_id=old.record.user_id,
            token_hash=token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        old.record = replace(old.record, rotated_to=successor)
        return successor

    async def revoke_family(
        self, *, org_id: OrgId, member: SessionId, reason: str, at: datetime
    ) -> Sequence[SessionId]:
        seen: set[SessionId] = set()
        frontier = [member]
        while frontier:
            current = frontier.pop()
            if current in seen or current not in self.rows:
                continue
            seen.add(current)
            row = self.rows[current]
            if row.record.rotated_to is not None:
                frontier.append(row.record.rotated_to)
            frontier.extend(
                other.record.session_id
                for other in self.rows.values()
                if other.record.rotated_to == current
            )
        revoked = []
        for session_id in seen:
            row = self.rows[session_id]
            if row.record.revoked_at is None:
                row.record = replace(row.record, revoked_at=at)
                row.revoked_reason = reason
                revoked.append(session_id)
        return revoked


class FakeUsers:
    """In-memory `AppUserStore`, recording what it was asked to create."""

    def __init__(self, *users: AppUserRecord) -> None:
        self.users = list(users)
        self.created: list[AppUserRecord] = []
        self.logins: list[tuple[UserId, datetime]] = []
        self._ids = Uuid7Generator()

    async def find_by_id(self, org_id: OrgId, user_id: UserId) -> AppUserRecord | None:
        return next((u for u in self.users if u.org_id == org_id and u.user_id == user_id), None)

    async def find_by_external_subject(
        self, org_id: OrgId, external_subject: str
    ) -> AppUserRecord | None:
        return next(
            (
                u
                for u in self.users
                if u.org_id == org_id and u.external_subject == external_subject
            ),
            None,
        )

    async def find_by_email(self, org_id: OrgId, email: str) -> AppUserRecord | None:
        return next(
            (u for u in self.users if u.org_id == org_id and u.email.lower() == email.lower()),
            None,
        )

    async def create(
        self,
        *,
        org_id: OrgId,
        provider_id: ProviderId,
        external_subject: str,
        email: str,
        display_name: str,
    ) -> AppUserRecord:
        record = AppUserRecord(
            user_id=UserId(self._ids.new()),
            org_id=org_id,
            email=email,
            display_name=display_name,
            external_subject=external_subject,
            is_active=True,
        )
        self.users.append(record)
        self.created.append(record)
        return record

    async def record_login(self, org_id: OrgId, user_id: UserId, at: datetime) -> None:
        self.logins.append((user_id, at))


# --------------------------------------------------------------------- fixtures


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def sessions() -> FakeSessions:
    return FakeSessions(Uuid7Generator())


@pytest.fixture
def users() -> FakeUsers:
    return FakeUsers()


def build_service(
    clock: FrozenClock,
    sessions: FakeSessions,
    users: FakeUsers,
    *orgs: OrgRecord,
) -> TokenService:
    return TokenService(
        orgs=FakeOrgs(*(orgs or (ACME,))),
        users=users,
        sessions=sessions,
        codec=PlatformTokenCodec(
            config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER),
            clock=clock,
            ids=Uuid7Generator(),
        ),
        clock=clock,
        refresh_ttl_s=REFRESH_TTL_S,
    )


@pytest.fixture
def service(clock: FrozenClock, sessions: FakeSessions, users: FakeUsers) -> TokenService:
    return build_service(clock, sessions, users, ACME, GLOBEX)


def oidc_subject(org: OrgRecord = ACME, **overrides: object) -> AuthenticatedSubject:
    base: dict[str, object] = {
        "org_id": org.org_id,
        "provider_id": PROVIDER_ID,
        "provider_kind": ProviderKind.OIDC,
        "external_subject": EXTERNAL_SUBJECT,
        "email": EMAIL,
        "display_name": "Ada Lovelace",
    }
    return AuthenticatedSubject(**{**base, **overrides})  # type: ignore[arg-type]


def claims_of(pair_access_token: str) -> AccessTokenClaims:
    """Decode without verifying — asserting on what the token *says*."""
    import jwt

    return AccessTokenClaims.from_claims(
        jwt.decode(pair_access_token, options={"verify_signature": False})
    )


# ------------------------------------------------------------------ the control


async def test_a_verified_subject_receives_a_working_pair(
    service: TokenService, sessions: FakeSessions, users: FakeUsers
) -> None:
    """Every denial below is one mutation away from this."""
    pair = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")

    assert pair.org_slug == "acme"
    assert pair.expires_in_s == 900
    assert pair.refresh_expires_at == NOW + timedelta(seconds=REFRESH_TTL_S)

    # The refresh credential names its tenant and carries a high-entropy secret.
    credential = RefreshCredential.parse(pair.refresh_token)
    assert credential.org_slug == "acme"
    assert len(credential.secret) >= 40, "32 random bytes, base64url"

    # Only the digest is stored. The plaintext exists in this process and nowhere
    # else, which is the whole reason `digest_token` is SHA-256 over a 256-bit
    # secret rather than argon2 over a password.
    row = sessions.rows[pair.session_id]
    assert row.record.refresh_token_hash == digest_token(pair.refresh_token)
    assert pair.refresh_token not in repr(row.record)

    claims = claims_of(pair.access_token)
    assert claims.org_id == ACME.org_id
    assert claims.session_id == pair.session_id
    assert claims.subject == users.users[0].user_id
    assert users.logins == [(claims.subject, NOW)], "`last_login_at` is stamped"


async def test_a_second_login_opens_a_second_independent_session(
    service: TokenService,
) -> None:
    """Two browsers are two chains. Signing out of one must not sign out the
    other, which is only true if the chains never share a row."""
    first = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    second = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")

    assert first.session_id != second.session_id
    assert first.refresh_token != second.refresh_token

    await service.revoke(first.refresh_token)
    assert await service.refresh(second.refresh_token), "the other device stays signed in"


# ------------------------------------------------------ rotation and the family


async def test_refresh_issues_a_new_pair_and_retires_the_old_token(
    service: TokenService, sessions: FakeSessions
) -> None:
    original = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    rotated = await service.refresh(original.refresh_token)

    assert rotated.refresh_token != original.refresh_token
    assert rotated.session_id != original.session_id
    # The chain is recorded forwards, which is what makes a replay detectable.
    assert sessions.rows[original.session_id].record.rotated_to == rotated.session_id
    assert sessions.rows[rotated.session_id].record.rotated_to is None
    # The new access token names the new session.
    assert claims_of(rotated.access_token).session_id == rotated.session_id


async def test_rotated_refresh_token_revokes_family(
    service: TokenService, sessions: FakeSessions
) -> None:
    """**The M3-level acceptance criterion.**

    A token that has already been rotated is proof of theft rather than a
    suspicion: the legitimate holder and the thief cannot both hold the current
    token, so one of them is replaying a copy — and nothing here can tell which.
    Refusing only the stale token would leave the thief holding the live one, so
    the whole chain dies and both parties log in again.
    """
    first = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    second = await service.refresh(first.refresh_token)
    third = await service.refresh(second.refresh_token)

    # The thief replays the *oldest* token, three links back.
    with pytest.raises(AuthenticationError) as denial:
        await service.refresh(first.refresh_token)
    assert denial.value.message == AUTHENTICATION_FAILED

    for link in (first, second, third):
        row = sessions.rows[link.session_id]
        assert row.record.revoked_at == NOW, f"session {link.session_id} survived the kill"
        assert row.revoked_reason == REVOKED_BY_REUSE

    # And the token the legitimate holder had is dead too — that is the cost, and
    # it is deliberate. Anything less leaves a live credential in a thief's hand.
    with pytest.raises(AuthenticationError):
        await service.refresh(third.refresh_token)


async def test_the_family_dies_from_any_member_not_just_the_root(
    service: TokenService, sessions: FakeSessions
) -> None:
    """Replaying a *middle* link has to reach the descendants as well as the
    ancestors, which is why the walk goes in both directions."""
    first = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    second = await service.refresh(first.refresh_token)
    third = await service.refresh(second.refresh_token)
    fourth = await service.refresh(third.refresh_token)

    with pytest.raises(AuthenticationError):
        await service.refresh(second.refresh_token)

    assert all(
        sessions.rows[link.session_id].record.revoked_at == NOW
        for link in (first, second, third, fourth)
    )


async def test_concurrent_use_of_one_refresh_token_is_treated_as_reuse(
    service: TokenService, sessions: FakeSessions
) -> None:
    """The race arrives through a different door and is the same evidence.

    Two requests read the same unrotated row; one wins the compare-and-set. The
    loser must not be handed a second live chain from one credential — so it kills
    the family instead. This is the backend half of TRACKER §5 M3.4 item 8: a
    frontend that fires N refreshes for N concurrent 401s revokes its own session,
    which is why the interceptor has to collapse them into one.
    """
    original = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    winner = await service.refresh(original.refresh_token)

    with pytest.raises(AuthenticationError):
        await service.refresh(original.refresh_token)

    assert sessions.rows[winner.session_id].record.revoked_at == NOW
    assert sessions.rows[winner.session_id].revoked_reason == REVOKED_BY_REUSE


async def test_an_expired_refresh_token_is_rejected_without_killing_the_family(
    service: TokenService, clock: FrozenClock, sessions: FakeSessions
) -> None:
    """Expiry is an ordinary end of life, not evidence of theft. Treating it as
    reuse would turn "came back after a fortnight" into a security incident."""
    pair = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    clock.advance(seconds=REFRESH_TTL_S)

    with pytest.raises(AuthenticationError):
        await service.refresh(pair.refresh_token)
    assert sessions.rows[pair.session_id].record.revoked_at is None
    assert sessions.rows[pair.session_id].revoked_reason is None


async def test_the_refresh_window_slides_on_every_rotation(
    service: TokenService, clock: FrozenClock
) -> None:
    """Recorded because it is a *weakness*, not a feature (TRACKER §4).

    An actively-used session never reaches an absolute end: each rotation buys
    another fourteen days. Capping it needs the chain root's `issued_at`, i.e. a
    walk to the root on every refresh or a `family_id` column, and neither is
    worth a migration until there is a policy that asks for it. Pinned here so the
    behaviour is a decision somebody made rather than one nobody noticed.
    """
    pair = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    clock.advance(days=13)
    rotated = await service.refresh(pair.refresh_token)
    assert rotated.refresh_expires_at == NOW + timedelta(days=13) + timedelta(seconds=REFRESH_TTL_S)


# ------------------------------------------------------------------- boundaries


async def test_refresh_token_for_one_org_is_useless_against_another(
    clock: FrozenClock, sessions: FakeSessions, users: FakeUsers
) -> None:
    """Two independent defences, and this asserts the *cryptographic* one.

    The row is org-scoped, so RLS and the explicit filter already confine the
    lookup. On top of that the slug is hashed together with the secret, so the
    same secret presented under another tenant's slug digests to something no row
    holds — the credential is bound to one tenant rather than merely stored
    beside it.
    """
    service = build_service(clock, sessions, users, ACME, GLOBEX)
    acme_pair = await service.issue_for_subject(subject=oidc_subject(ACME), org_slug="acme")
    secret = RefreshCredential.parse(acme_pair.refresh_token).secret

    # The same secret, re-labelled with the other tenant's slug.
    with pytest.raises(AuthenticationError) as denial:
        await service.refresh(RefreshCredential(org_slug="globex", secret=secret).render())
    assert denial.value.message == AUTHENTICATION_FAILED

    # It is genuinely the hash that differs, not just the org-scoped read.
    assert digest_token(f"globex.{secret}") != digest_token(f"acme.{secret}")
    # And the acme session is untouched: a probe from another tenant must not be
    # able to revoke a family it cannot reach.
    assert sessions.rows[acme_pair.session_id].record.revoked_at is None
    assert await service.refresh(acme_pair.refresh_token)


async def test_a_refresh_token_survives_the_orgs_capitalisation(
    service: TokenService,
) -> None:
    """`org.slug` is CITEXT. The digest is taken against the canonical slug from
    the row, so a client echoing "ACME" back still refreshes — while still being
    a different tenant's slug when it genuinely is one."""
    pair = await service.issue_for_subject(subject=oidc_subject(), org_slug="ACME")
    assert pair.org_slug == "acme"
    secret = RefreshCredential.parse(pair.refresh_token).secret
    assert await service.refresh(f"ACME.{secret}")


async def test_a_deactivated_user_cannot_refresh(service: TokenService, users: FakeUsers) -> None:
    """Otherwise deactivation takes up to fourteen days to bite, which is the
    same revocation hole a `roles` claim opens, one layer out."""
    pair = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    users.users[0] = replace(users.users[0], is_active=False)

    with pytest.raises(AuthenticationError):
        await service.refresh(pair.refresh_token)


@pytest.mark.parametrize(
    "presented",
    ["", "no-separator", "acme.", ".secret", "acme.wrong-secret", "nosuchorg.secret"],
)
async def test_a_malformed_or_unknown_refresh_token_is_one_denial(
    service: TokenService, presented: str
) -> None:
    """Malformed, unknown org, and wrong secret must read identically. Any
    difference is a free tenant-enumeration oracle for an unauthenticated caller.
    """
    with pytest.raises(AuthenticationError) as denial:
        await service.refresh(presented)
    assert denial.value.message == AUTHENTICATION_FAILED


async def test_issuing_refuses_a_subject_from_a_different_org(
    service: TokenService,
) -> None:
    """The slug and the subject's org id must agree. They can only differ if a
    caller composed a subject with a slug from somewhere else."""
    with pytest.raises(AuthenticationError):
        await service.issue_for_subject(subject=oidc_subject(GLOBEX), org_slug="acme")


# ----------------------------------------------------------------------- revoke


async def test_revoke_kills_the_whole_chain_and_says_nothing(
    service: TokenService, sessions: FakeSessions
) -> None:
    """Sign-out. The whole chain, because the previous links are tokens that
    device has held and leaving them live defeats the point of signing out."""
    first = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    second = await service.refresh(first.refresh_token)

    assert await service.revoke(second.refresh_token) is None

    for link in (first, second):
        assert sessions.rows[link.session_id].record.revoked_at == NOW
        assert sessions.rows[link.session_id].revoked_reason == REVOKED_BY_SIGN_OUT
    with pytest.raises(AuthenticationError):
        await service.refresh(second.refresh_token)


@pytest.mark.parametrize(
    "presented", ["", "garbage", "acme.never-issued", "nosuchorg.secret", "acme."]
)
async def test_revoke_is_silent_for_a_token_it_cannot_find(
    service: TokenService, presented: str
) -> None:
    """RFC 7009 §2.2, and the reason matters: an endpoint that answers 401 for an
    unknown token and 204 for a known one is a free oracle for testing stolen
    credentials — and the caller is unauthenticated, because presenting the token
    *is* the authentication.
    """
    assert await service.revoke(presented) is None


# --------------------------------------------------- just-in-time provisioning


async def test_a_first_login_provisions_a_user_with_no_roles(
    service: TokenService, users: FakeUsers
) -> None:
    """Provisioning grants identity, never authority.

    The decision is recorded in `TokenService._resolve_user`: refusing to
    provision would mean nobody but the bootstrap admin can ever sign in, which
    is a reason to share an account rather than a security control. What makes it
    safe is that the new row gets no `role_binding` and no `user_tag`, so the
    user can sign in and do nothing at all until M3.6 grants something.
    """
    await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")

    assert len(users.created) == 1
    created = users.created[0]
    assert created.external_subject == EXTERNAL_SUBJECT
    assert created.email == EMAIL
    assert created.display_name == "Ada Lovelace"
    assert created.org_id == ACME.org_id
    # `AppUserRecord` carries no permissions field at all — authority is not a
    # thing this layer can grant even by accident.
    assert not hasattr(created, "permissions")


async def test_a_second_login_reuses_the_provisioned_user(
    service: TokenService, users: FakeUsers
) -> None:
    first = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    second = await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")

    assert len(users.created) == 1
    assert claims_of(first.access_token).subject == claims_of(second.access_token).subject


async def test_a_changed_email_does_not_fork_the_account(
    service: TokenService, users: FakeUsers
) -> None:
    """Matching is on `external_subject`. Somebody who changes their address at
    the IdP is the same person, and a system that matched on email would hand
    them a brand-new empty account instead."""
    await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    await service.issue_for_subject(
        subject=oidc_subject(email="ada.lovelace@example.test"), org_slug="acme"
    )
    assert len(users.created) == 1


async def test_an_email_belonging_to_another_subject_is_refused(
    service: TokenService, users: FakeUsers
) -> None:
    """The other half of matching on `external_subject`.

    An IdP email is a mutable and frequently-unverified attribute of an account
    *there*; auto-linking on it lets whoever can set that address inherit a local
    user. So this denies, and linking is left as an administrative action with a
    human in it.
    """
    await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")

    with pytest.raises(AuthenticationError) as denial:
        await service.issue_for_subject(
            subject=oidc_subject(external_subject="a-different-keycloak-subject"),
            org_slug="acme",
        )
    assert denial.value.message == AUTHENTICATION_FAILED
    assert len(users.created) == 1


async def test_a_subject_with_no_email_is_refused_rather_than_invented(
    service: TokenService, users: FakeUsers
) -> None:
    """`app_user.email` is NOT NULL and uniquely indexed per org. Synthesising an
    address would create an unaddressable account that collides the moment the
    IdP starts asserting a real one."""
    with pytest.raises(AuthenticationError):
        await service.issue_for_subject(subject=oidc_subject(email=None), org_slug="acme")
    assert users.created == []


async def test_a_deactivated_user_cannot_sign_in_again(
    service: TokenService, users: FakeUsers
) -> None:
    """And is not silently re-provisioned around, which is what matching on
    `external_subject` before creating anything guarantees."""
    await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    users.users[0] = replace(users.users[0], is_active=False)

    with pytest.raises(AuthenticationError):
        await service.issue_for_subject(subject=oidc_subject(), org_slug="acme")
    assert len(users.created) == 1


async def test_an_internally_authenticated_subject_is_never_provisioned(
    service: TokenService, users: FakeUsers
) -> None:
    """`InternalProvider` already resolved a local row to check the password
    against, so there is nothing to create — and creating anything here would
    mean a password login could mint a *second* account for the same person."""
    existing = AppUserRecord(
        user_id=UserId(uuid4()),
        org_id=ACME.org_id,
        email="grace@example.test",
        display_name="Grace Hopper",
        external_subject=None,
        is_active=True,
    )
    users.users.append(existing)
    pair = await service.issue_for_subject(
        subject=AuthenticatedSubject(
            org_id=ACME.org_id,
            provider_id=PROVIDER_ID,
            provider_kind=ProviderKind.INTERNAL,
            user_id=existing.user_id,
        ),
        org_slug="acme",
    )
    assert users.created == []
    assert claims_of(pair.access_token).subject == existing.user_id
