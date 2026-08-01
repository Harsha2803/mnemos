"""What the provider layer needs to read, expressed as ports.

The strategies need three rows: the org named by the credential, the
``identity_provider`` row that says which strategy to build, and — for internal
auth — the ``app_user`` row holding the password hash. They get them through these
narrow ports rather than through a SQLAlchemy session, for two reasons.

*Layering.* ADAPTATION §5 puts persistence in ``adapters``. Ports here, the
SQLAlchemy implementations in ``features/identity/adapters/directory.py``, and
``providers/`` imports no ORM at all — pinned by
``test_providers_import_no_sqlalchemy_and_no_fastapi``.

*Testability of the thing that matters.* What these strategies actually decide is
"is this argon2 hash a match", "is this signature valid, from the configured
issuer, for our client". None of that is a property of Postgres — unlike tenant
isolation, where a fake would only prove the fake isolates. Reading a row through
a port lets those decisions be tested in milliseconds without a container, and the
SQL that fills the record is exercised where SQL is worth exercising.

The records are flat value objects, not ORM rows: a provider that held a live
``AppUser`` could lazy-load a relationship and issue a query from inside an
authentication decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from mnemos.features.identity.domain import OrgId, ProviderId, UserId


@dataclass(frozen=True, slots=True)
class OrgRecord:
    """The tenant a credential named.

    ``org`` is the only table without RLS (it is the table the policies are
    *about*), which is what lets this one lookup happen before any tenant is
    known — and is why the whole authentication path needs no ``BYPASSRLS``.

    ``default_provider_slug`` comes from ``org.settings`` rather than a column, so
    an org can name its default login method without a migration.
    """

    org_id: OrgId
    slug: str
    is_active: bool
    default_provider_slug: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """One ``identity_provider`` row, as the factory reads it.

    ``kind`` stays a raw ``str``. It is CHECK-constrained in the database, but the
    factory must survive reading a value it does not recognise — the check
    constraint could be relaxed by a later migration before this code learns the
    new kind — and "unknown kind" has to be a denial, not a ``ValueError`` from an
    enum constructor halfway up the stack.
    """

    provider_id: ProviderId
    org_id: OrgId
    slug: str
    kind: str
    is_enabled: bool
    issuer_public: str | None = None
    issuer_internal: str | None = None
    client_id: str | None = None


@dataclass(frozen=True, slots=True)
class UserCredentialRecord:
    """The parts of ``app_user`` that authentication decides on. Nothing else.

    ``password_hash`` is ``None`` for a user that exists only in an external IdP.
    That is a legitimate row, not a broken one, and it must not be able to
    password-authenticate.
    """

    user_id: UserId
    org_id: OrgId
    email: str
    display_name: str
    password_hash: str | None
    is_active: bool


class OrgDirectory(Protocol):
    """Reads ``org`` and ``identity_provider``. Used by the factory before any
    caller is authenticated, which is why every method is deny-tolerant: a missing
    row is ``None``, never an exception."""

    async def find_org(self, slug: str) -> OrgRecord | None: ...

    async def find_provider(self, org_id: OrgId, slug: str) -> ProviderRecord | None: ...

    async def list_enabled_providers(self, org_id: OrgId) -> Sequence[ProviderRecord]: ...


class UserDirectory(Protocol):
    """Reads ``app_user`` within one org.

    The org is a parameter rather than ambient state so the implementation can
    scope its transaction to that tenant and the RLS policy is doing real work
    underneath the explicit filter.
    """

    async def find_by_email(self, org_id: OrgId, email: str) -> UserCredentialRecord | None: ...
