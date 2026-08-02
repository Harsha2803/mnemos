"""SQLAlchemy behind ``SessionStore`` and ``AppUserStore``.

All the ORM for the token path lives here, so ``application/tokens.py`` stays a
use case and ``providers/`` stays free of persistence (ADAPTATION §5, pinned by a
subprocess test).

Every statement runs inside ``Database.session(org_id=...)``, so `app.current_org`
is bound for the transaction and row-level security applies underneath the
explicit ``org_id`` predicate. **No ``elevated_session()`` anywhere**: the org is
resolved from the credential before anything here is called, which is the whole
reason M3.2 put the tenant inside the credential.

Two statements here are worth reading closely, because each is doing something a
plain ORM call cannot:

*The rotation is a compare-and-set.* Inserting the successor and claiming the
predecessor happen in one transaction, and the claim is
``UPDATE ... WHERE rotated_to IS NULL AND revoked_at IS NULL``. A read-then-write
would let two concurrent presentations of one refresh token both observe an
unrotated row and both succeed, producing two live chains from one credential —
which is exactly the state the family kill exists to make impossible.

*The family walk is a recursive CTE.* ``session.rotated_to`` is a forward
pointer, so reaching a whole chain from an arbitrary member means walking
*both* directions: descendants via ``s.rotated_to = f.id`` and ancestors via
``s.id = f.rotated_to``. Done in the database rather than in a Python loop
because a loop is one round trip per link — a fourteen-day chain refreshed every
fifteen minutes is over a thousand of them — and because the revoke has to be
one statement to be atomic. ``UNION`` rather than ``UNION ALL`` is what makes it
terminate: Postgres discards rows already produced, so the two directions meeting
in the middle is a fixpoint rather than a loop.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mnemos.core.ids import IdGenerator
from mnemos.features.identity.adapters.models import AppUser
from mnemos.features.identity.adapters.models import Session as SessionRow
from mnemos.features.identity.application.tokens import AppUserRecord, SessionRecord
from mnemos.features.identity.domain import OrgId, ProviderId, SessionId, UserId
from mnemos.features.identity.providers import denied
from mnemos.platform.db import Database

#: Walks `rotated_to` in both directions from one member, then revokes everything
#: it reached that is not revoked already. See the module docstring for why this
#: is one statement and why `UNION` (not `UNION ALL`) terminates it.
#:
#: `org_id` is repeated in the recursive term as well as the anchor: RLS would
#: confine the walk anyway, but a chain must not be able to leave its tenant even
#: in principle, and the predicate is what lets the planner use the index.
_REVOKE_FAMILY = text("""
WITH RECURSIVE family(id, rotated_to) AS (
        SELECT s.id, s.rotated_to
          FROM session s
         WHERE s.org_id = :org_id AND s.id = :member
    UNION
        SELECT s.id, s.rotated_to
          FROM session s
          JOIN family f ON s.rotated_to = f.id OR s.id = f.rotated_to
         WHERE s.org_id = :org_id
)
UPDATE session AS t
   SET revoked_at = :at, revoked_reason = :reason
  FROM family
 WHERE t.id = family.id
   AND t.org_id = :org_id
   AND t.revoked_at IS NULL
RETURNING t.id
""")


class _RotationLostError(Exception):
    """Raised inside the rotation transaction to roll it back.

    A private signal rather than an early ``return``: the successor row has
    already been inserted by the time the compare-and-set fails, and it must not
    survive. Raising is how ``Database.session()`` is told to roll back — calling
    ``session.rollback()`` by hand and then falling out of the context manager
    leaves it trying to commit a transaction that is already gone.
    """


class SqlSessionStore:
    """``SessionStore`` over Postgres."""

    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        # Injected rather than calling `uuid7()` inline (CodingStandards §5), so
        # a test can pin the ids a rotation chain gets.
        self._ids = ids

    async def find_by_token_hash(self, org_id: OrgId, token_hash: str) -> SessionRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(SessionRow).where(
                    SessionRow.org_id == org_id,
                    SessionRow.refresh_token_hash == token_hash,
                )
            )
        return _session_record(row) if row is not None else None

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
        new_id = self._ids.new()
        async with self._db.session(org_id=org_id) as session:
            session.add(
                SessionRow(
                    id=new_id,
                    org_id=org_id,
                    user_id=user_id,
                    refresh_token_hash=token_hash,
                    issued_at=issued_at,
                    expires_at=expires_at,
                    user_agent=user_agent,
                    ip_address=ip_address,
                )
            )
        return SessionId(new_id)

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
        new_id = self._ids.new()
        try:
            async with self._db.session(org_id=org_id) as session:
                session.add(
                    SessionRow(
                        id=new_id,
                        org_id=org_id,
                        user_id=await self._user_of(session, org_id, predecessor),
                        refresh_token_hash=token_hash,
                        issued_at=issued_at,
                        expires_at=expires_at,
                        user_agent=user_agent,
                        ip_address=ip_address,
                    )
                )
                # The successor must exist before the FK on `rotated_to` can
                # point at it.
                await session.flush()
                claimed = await session.scalar(
                    update(SessionRow)
                    .where(
                        SessionRow.id == predecessor,
                        SessionRow.org_id == org_id,
                        SessionRow.rotated_to.is_(None),
                        SessionRow.revoked_at.is_(None),
                    )
                    .values(rotated_to=new_id)
                    # `RETURNING` rather than `rowcount`: it says in the statement
                    # itself which row was claimed, and "no row came back" is the
                    # lost race without depending on a driver's row counting.
                    .returning(SessionRow.id)
                )
                if claimed is None:
                    raise _RotationLostError
        except _RotationLostError:
            return None
        return SessionId(new_id)

    async def revoke_family(
        self, *, org_id: OrgId, member: SessionId, reason: str, at: datetime
    ) -> Sequence[SessionId]:
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                _REVOKE_FAMILY,
                {"org_id": org_id, "member": member, "at": at, "reason": reason},
            )
            return [SessionId(row_id) for (row_id,) in result.all()]

    @staticmethod
    async def _user_of(session: AsyncSession, org_id: OrgId, predecessor: SessionId) -> uuid.UUID:
        """The predecessor's owner, read inside the rotation transaction.

        Read here rather than carried in from the caller so the successor cannot
        be attributed to a different user than the row it descends from, however
        the call site is later refactored.
        """
        owner = await session.scalar(
            select(SessionRow.user_id).where(
                SessionRow.id == predecessor, SessionRow.org_id == org_id
            )
        )
        if owner is None:
            raise denied(f"session {predecessor} vanished mid-rotation")
        return owner


class SqlAppUserStore:
    """``AppUserStore`` over Postgres."""

    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def find_by_id(self, org_id: OrgId, user_id: UserId) -> AppUserRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(AppUser).where(AppUser.org_id == org_id, AppUser.id == user_id)
            )
        return _user_record(row) if row is not None else None

    async def find_by_external_subject(
        self, org_id: OrgId, external_subject: str
    ) -> AppUserRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(AppUser).where(
                    AppUser.org_id == org_id,
                    AppUser.external_subject == external_subject,
                )
            )
        return _user_record(row) if row is not None else None

    async def find_by_email(self, org_id: OrgId, email: str) -> AppUserRecord | None:
        # `email` is CITEXT: the comparison is case-insensitive in the database
        # and must not be pre-lowered here, or it would diverge from
        # `uq_app_user_org_id_email` and let two "different" users collide.
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(AppUser).where(AppUser.org_id == org_id, AppUser.email == email)
            )
        return _user_record(row) if row is not None else None

    async def create(
        self,
        *,
        org_id: OrgId,
        provider_id: ProviderId,
        external_subject: str,
        email: str,
        display_name: str,
    ) -> AppUserRecord:
        """Provision a user for an externally-authenticated subject.

        ``password_hash`` stays NULL, which is not an omission: `InternalProvider`
        refuses to authenticate a row with no hash (M3.2), so a user created here
        can only ever arrive through the IdP that vouched for them. No
        `role_binding` and no `user_tag` are written either — provisioning grants
        identity, never authority.
        """
        new_id = self._ids.new()
        try:
            async with self._db.session(org_id=org_id) as session:
                session.add(
                    AppUser(
                        id=new_id,
                        org_id=org_id,
                        email=email,
                        display_name=display_name,
                        password_hash=None,
                        provider_id=provider_id,
                        external_subject=external_subject,
                    )
                )
        except IntegrityError as exc:
            # `uq_app_user_org_id_email` under a concurrent first login for the
            # same person. The application already checks for a collision; this
            # closes the window between that check and this insert, and it must
            # be a denial rather than a 500 with a constraint name in it.
            raise denied(f"could not provision {email!r}: {exc.orig!r}") from exc
        return AppUserRecord(
            user_id=UserId(new_id),
            org_id=org_id,
            email=email,
            display_name=display_name,
            external_subject=external_subject,
            is_active=True,
        )

    async def record_login(self, org_id: OrgId, user_id: UserId, at: datetime) -> None:
        """Stamp `last_login_at`. Its own transaction, because a failure to
        record a timestamp must not roll back the session that was just opened."""
        async with self._db.session(org_id=org_id) as session:
            await session.execute(
                update(AppUser)
                .where(AppUser.org_id == org_id, AppUser.id == user_id)
                .values(last_login_at=at)
            )


def _session_record(row: SessionRow) -> SessionRecord:
    return SessionRecord(
        session_id=SessionId(row.id),
        org_id=OrgId(row.org_id),
        user_id=UserId(row.user_id),
        refresh_token_hash=row.refresh_token_hash,
        rotated_to=SessionId(row.rotated_to) if row.rotated_to is not None else None,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def _user_record(row: AppUser) -> AppUserRecord:
    return AppUserRecord(
        user_id=UserId(row.id),
        org_id=OrgId(row.org_id),
        email=row.email,
        display_name=row.display_name,
        external_subject=row.external_subject,
        is_active=row.is_active,
    )
