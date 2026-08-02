"""SQLAlchemy behind ``PrincipalRepository``: the per-request authority read.

All the ORM for the guard path lives here, so
``application/principals.py`` stays a use case (ADAPTATION §5, pinned by a
subprocess test).

**One transaction, four statements, one tenant.** Everything runs inside
``Database.session(org_id=...)`` with ``app.current_org`` bound, so row-level
security is underneath every predicate and the read cannot wander into another
tenant even if a join were written wrong. There is no ``elevated_session()``
here and there must never be: the org comes out of a token *we* signed, before
anything is read.

The four statements are kept in one transaction rather than fired separately —
unlike ``directory.py``, where each read is its own — because these must be
mutually consistent. Roles read before a revocation and tags read after it would
produce a principal that never existed in the database, and that principal is
the input to an authorization decision.

``org.slug`` is joined in because the sidebar has to name the tenant. ``org`` is
the one table without an RLS policy (it is what every other policy compares
*against*), so reading it inside a scoped transaction costs nothing and needs no
privilege.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from mnemos.features.identity.adapters.models import (
    AppUser,
    Org,
    Role,
    RoleBinding,
    Tag,
    UserTag,
)
from mnemos.features.identity.adapters.models import Session as SessionRow
from mnemos.features.identity.application.principals import UserAuthority, flatten_grants
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.platform.db import Database


class SqlPrincipalRepository:
    """``PrincipalRepository`` over Postgres."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def load_authority(self, org_id: OrgId, user_id: UserId) -> UserAuthority | None:
        async with self._db.session(org_id=org_id) as session:
            user = await session.scalar(
                select(AppUser).where(AppUser.org_id == org_id, AppUser.id == user_id)
            )
            if user is None:
                return None

            org_slug = await session.scalar(select(Org.slug).where(Org.id == org_id))
            if org_slug is None:  # pragma: no cover - an app_user cannot outlive its org
                return None

            # Every role bound to this user, in slug order so a principal built
            # twice from the same rows is the same principal — which is what
            # makes a permission set worth logging or diffing.
            grant_lists = (
                await session.scalars(
                    select(Role.permissions)
                    .join(RoleBinding, RoleBinding.role_id == Role.id)
                    .where(
                        RoleBinding.org_id == org_id,
                        RoleBinding.user_id == user_id,
                        Role.org_id == org_id,
                    )
                    .order_by(Role.slug)
                )
            ).all()

            tags = (
                await session.scalars(
                    select(Tag.slug)
                    .join(UserTag, UserTag.tag_id == Tag.id)
                    .where(
                        UserTag.org_id == org_id,
                        UserTag.user_id == user_id,
                        Tag.org_id == org_id,
                    )
                    .order_by(Tag.slug)
                )
            ).all()

            return UserAuthority(
                user_id=UserId(user.id),
                org_id=OrgId(user.org_id),
                org_slug=org_slug,
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                permissions=flatten_grants(list(grant_lists)),
                tags=tuple(tags),
            )

    async def session_is_live(self, org_id: OrgId, session_id: SessionId, at: datetime) -> bool:
        """Revoked or expired is dead; *rotated* is not.

        Rotation retires a refresh token and opens a successor row; the access
        token minted against the predecessor is still a legitimate credential
        until its own ``exp``. Treating a rotated row as dead would log the user
        out on every refresh, which is the opposite of what refresh is for.
        """
        async with self._db.session(org_id=org_id) as session:
            found = await session.scalar(
                select(SessionRow.id).where(
                    SessionRow.org_id == org_id,
                    SessionRow.id == session_id,
                    SessionRow.revoked_at.is_(None),
                    SessionRow.expires_at > at,
                )
            )
        return found is not None
