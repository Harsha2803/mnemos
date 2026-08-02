"""The SQLAlchemy side of the bootstrap: two transactions, one of them elevated.

This module is where ``Database.elevated_session()`` is actually called, and it is
the only call site in the system. The application layer decides *how much* runs
elevated (:mod:`mnemos.features.identity.application.bootstrap`); this decides
*how*, and keeps the ORM out of the use case.

**Why the org insert is the elevated one.** ``org`` is the one table migration
`0004` deliberately left without a policy — it is what every other policy compares
against — so today this ``INSERT`` would also succeed on an ordinary unprivileged
session. It runs under ``SET LOCAL ROLE`` anyway for two reasons that outlive that
fact. It is the only statement in the system that provably *cannot* carry
``app.current_org``, because the value it would carry is the value it is
generating; naming that in the code is worth more than saving a statement. And if
``org`` is ever brought under a policy — the obvious next step if orgs gain a
parent, a reseller or a soft-delete — this call site keeps working while an
ordinary session would start failing a ``WITH CHECK`` at bootstrap time, which is
the worst possible moment to discover it.

**Everything else is deliberately *not* elevated.** The admin user, the roles, the
provider rows and the binding are all inserted with the GUC bound to the org that
transaction is scoped to, so a bug that computed the wrong ``org_id`` is rejected
by the policy's ``WITH CHECK`` instead of committed. Widening the elevated
transaction to cover them would be one line and would silently remove that check
from the only code path that writes an org's first rows.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mnemos.core.ids import DEFAULT_ID_GENERATOR, IdGenerator
from mnemos.features.identity.adapters.directory import DEFAULT_PROVIDER_SETTING
from mnemos.features.identity.adapters.models import (
    AppUser,
    IdentityProvider,
    Org,
    Role,
    RoleBinding,
)
from mnemos.features.identity.application.bootstrap import (
    BootstrapWriter,
    Ensured,
    EnsuredOrg,
    ProviderSpec,
)
from mnemos.features.identity.domain import OrgId, ProviderId, RoleId, SystemRole, UserId
from mnemos.platform.db import Database

#: ``role_binding.scope`` for an org-wide binding, matching the column's server
#: default. Spelled out rather than left to the default so the row this command
#: writes is fully described by the code that writes it.
ORG_WIDE_SCOPE = "*"


class SqlBootstrapWriter:
    """Row writes against one already-open session. Owns no transaction."""

    def __init__(self, session: AsyncSession, *, ids: IdGenerator = DEFAULT_ID_GENERATOR) -> None:
        self._session = session
        self._ids = ids

    async def ensure_org(self, *, slug: str, name: str) -> EnsuredOrg:
        existing = await self._session.scalar(select(Org).where(Org.slug == slug))
        if existing is not None:
            # `existing.name`, not `name`: the row is not renamed, so reporting
            # the requested name would report a write that did not happen.
            return EnsuredOrg(id=OrgId(existing.id), name=existing.name, created=False)

        org = Org(id=self._ids.new(), slug=slug, name=name, is_active=True, settings={})
        self._session.add(org)
        # Flushed rather than left to the commit: the caller needs the id for the
        # session that follows, and `org.id` is only knowable once the INSERT has
        # actually been sent.
        await self._session.flush()
        return EnsuredOrg(id=OrgId(org.id), name=org.name, created=True)

    async def ensure_role(self, *, org_id: OrgId, role: SystemRole) -> Ensured[RoleId]:
        existing = await self._session.scalar(
            select(Role).where(Role.org_id == org_id, Role.slug == role.slug)
        )
        if existing is not None:
            # The grants of an existing role are left exactly as they are — see
            # the idempotency paragraph in the application module. A role whose
            # permissions were edited must not be silently rewritten by a re-run.
            return Ensured(id=RoleId(existing.id), created=False)

        row = Role(
            id=self._ids.new(),
            org_id=org_id,
            slug=role.slug,
            name=role.name,
            permissions=list(role.grants),
            is_system=True,
        )
        self._session.add(row)
        await self._session.flush()
        return Ensured(id=RoleId(row.id), created=True)

    async def ensure_provider(self, *, org_id: OrgId, spec: ProviderSpec) -> Ensured[ProviderId]:
        existing = await self._session.scalar(
            select(IdentityProvider).where(
                IdentityProvider.org_id == org_id, IdentityProvider.slug == spec.slug
            )
        )
        if existing is not None:
            return Ensured(id=ProviderId(existing.id), created=False)

        row = IdentityProvider(
            id=self._ids.new(),
            org_id=org_id,
            slug=spec.slug,
            kind=spec.kind.value,
            display_name=spec.display_name,
            is_enabled=spec.is_enabled,
            issuer_public=spec.issuer_public,
            issuer_internal=spec.issuer_internal,
            client_id=spec.client_id,
            # `mnemos-web` is a public client with PKCE and has no secret to
            # store. A row that carried an empty `client_secret_enc` would look
            # like a secret nobody had encrypted yet.
            client_secret_enc=None,
            config={},
        )
        self._session.add(row)
        await self._session.flush()
        return Ensured(id=ProviderId(row.id), created=True)

    async def ensure_user(
        self,
        *,
        org_id: OrgId,
        email: str,
        display_name: str,
        password_hash: str,
        provider_id: ProviderId,
    ) -> Ensured[UserId]:
        # `email` is CITEXT: the comparison is case-insensitive in the database
        # and must not be pre-lowered here, or it would diverge from
        # `uq_app_user_org_id_email` and a second run would try to insert a
        # duplicate that the unique index then rejects.
        existing = await self._session.scalar(
            select(AppUser).where(AppUser.org_id == org_id, AppUser.email == email)
        )
        if existing is not None:
            # Crucially, the password hash is **not** rewritten. This command is
            # the kind that ends up in a deploy script; rewriting the hash would
            # reset the administrator's password on every release.
            return Ensured(id=UserId(existing.id), created=False)

        row = AppUser(
            id=self._ids.new(),
            org_id=org_id,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            provider_id=provider_id,
            external_subject=None,
            is_active=True,
        )
        self._session.add(row)
        await self._session.flush()
        return Ensured(id=UserId(row.id), created=True)

    async def ensure_role_binding(
        self, *, org_id: OrgId, user_id: UserId, role_id: RoleId
    ) -> Ensured[uuid.UUID]:
        existing = await self._session.scalar(
            select(RoleBinding).where(
                RoleBinding.user_id == user_id,
                RoleBinding.role_id == role_id,
                RoleBinding.scope == ORG_WIDE_SCOPE,
            )
        )
        if existing is not None:
            return Ensured(id=existing.id, created=False)

        row = RoleBinding(
            id=self._ids.new(),
            org_id=org_id,
            user_id=user_id,
            role_id=role_id,
            scope=ORG_WIDE_SCOPE,
        )
        self._session.add(row)
        await self._session.flush()
        return Ensured(id=row.id, created=True)

    async def ensure_default_provider(self, *, org_id: OrgId, provider_slug: str) -> bool:
        org = await self._session.scalar(select(Org).where(Org.id == org_id))
        if org is None:  # pragma: no cover - the caller just created or read it
            msg = f"org {org_id} disappeared between transactions"
            raise RuntimeError(msg)

        if DEFAULT_PROVIDER_SETTING in org.settings:
            return False

        # Assigned as a new dict, not mutated in place: SQLAlchemy compares JSONB
        # attributes by identity for change detection, so `org.settings[k] = v`
        # is a write that never reaches the database.
        org.settings = {**org.settings, DEFAULT_PROVIDER_SETTING: provider_slug}
        await self._session.flush()
        return True


class SqlBootstrapStore:
    """Opens the two transactions the bootstrap runs in."""

    def __init__(self, db: Database, *, ids: IdGenerator = DEFAULT_ID_GENERATOR) -> None:
        self._db = db
        self._ids = ids

    @asynccontextmanager
    async def without_a_tenant(self) -> AsyncIterator[BootstrapWriter]:
        async with self._db.elevated_session() as session:
            yield SqlBootstrapWriter(session, ids=self._ids)

    @asynccontextmanager
    async def scoped_to(self, org_id: OrgId) -> AsyncIterator[BootstrapWriter]:
        async with self._db.session(org_id=org_id) as session:
            yield SqlBootstrapWriter(session, ids=self._ids)
