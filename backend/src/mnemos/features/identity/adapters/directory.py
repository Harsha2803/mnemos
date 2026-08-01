"""SQLAlchemy implementations of the provider layer's read ports.

All the ORM in the authentication path lives here, so ``providers/`` stays free of
it (ADAPTATION §5, pinned by a subprocess test).

**Transaction scoping is the interesting part.** ``org`` carries no RLS policy —
it is the table every other policy compares against — so :meth:`SqlOrgDirectory.find_org`
runs on an unscoped session and needs no privilege. Everything after it runs on a
session with ``app.current_org`` bound to the org just resolved, so the RLS policy
is doing real work underneath the explicit ``org_id`` filter rather than being
bypassed for the convenience of an unauthenticated caller. That is why the
authentication path never calls ``elevated_session()``.

Each method opens its own short transaction rather than sharing one across the
login. Two or three sub-millisecond reads is the right trade for not having a
session's lifetime entangled with a strategy object's, and none of these reads
need to be mutually consistent — a provider disabled between the factory's read
and the user lookup denies on the next request, which is soon enough.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from mnemos.features.identity.adapters.models import AppUser, IdentityProvider, Org
from mnemos.features.identity.domain import OrgId, ProviderId, UserId
from mnemos.features.identity.providers.ports import (
    OrgRecord,
    ProviderRecord,
    UserCredentialRecord,
)
from mnemos.platform.db import Database

#: Key in `org.settings` naming the org's default login method. A JSONB setting
#: rather than a column: which provider an org logs in with by default is
#: configuration, and it should not cost a migration to express.
DEFAULT_PROVIDER_SETTING = "default_provider"


class SqlOrgDirectory:
    """Reads ``org`` and ``identity_provider`` for the factory."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def find_org(self, slug: str) -> OrgRecord | None:
        # Unscoped deliberately: this call is what *determines* the scope, and
        # `org` is the one table RLS does not cover.
        async with self._db.session() as session:
            org = await session.scalar(select(Org).where(Org.slug == slug))
        if org is None:
            return None
        default = org.settings.get(DEFAULT_PROVIDER_SETTING)
        return OrgRecord(
            org_id=OrgId(org.id),
            slug=org.slug,
            is_active=org.is_active,
            default_provider_slug=default if isinstance(default, str) and default else None,
        )

    async def find_provider(self, org_id: OrgId, slug: str) -> ProviderRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(IdentityProvider).where(
                    IdentityProvider.org_id == org_id,
                    IdentityProvider.slug == slug,
                )
            )
        return _provider_record(row) if row is not None else None

    async def list_enabled_providers(self, org_id: OrgId) -> Sequence[ProviderRecord]:
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(IdentityProvider)
                    .where(
                        IdentityProvider.org_id == org_id,
                        IdentityProvider.is_enabled.is_(True),
                    )
                    .order_by(IdentityProvider.slug)
                )
            ).all()
        return [_provider_record(row) for row in rows]


class SqlUserDirectory:
    """Reads the credential-bearing columns of ``app_user``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def find_by_email(self, org_id: OrgId, email: str) -> UserCredentialRecord | None:
        # `email` is CITEXT, so the comparison is case-insensitive in the database
        # and must not be pre-lowered here — that would diverge from the unique
        # index `uq_app_user_org_id_email` and let two "different" users collide.
        async with self._db.session(org_id=org_id) as session:
            user = await session.scalar(
                select(AppUser).where(AppUser.org_id == org_id, AppUser.email == email)
            )
        if user is None:
            return None
        return UserCredentialRecord(
            user_id=UserId(user.id),
            org_id=OrgId(user.org_id),
            email=user.email,
            display_name=user.display_name,
            password_hash=user.password_hash,
            is_active=user.is_active,
        )


def _provider_record(row: IdentityProvider) -> ProviderRecord:
    return ProviderRecord(
        provider_id=ProviderId(row.id),
        org_id=OrgId(row.org_id),
        slug=row.slug,
        kind=row.kind,
        is_enabled=row.is_enabled,
        issuer_public=row.issuer_public,
        issuer_internal=row.issuer_internal,
        client_id=row.client_id,
    )
