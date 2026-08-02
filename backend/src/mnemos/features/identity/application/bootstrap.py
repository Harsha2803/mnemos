"""The first org, its admin, the system roles, and the rows that make login work.

Every other write in this system happens inside a tenant. This one cannot: the
first ``INSERT`` is the org that everything afterwards would be scoped to. That
chicken-and-egg is the whole reason :meth:`~mnemos.platform.db.Database.elevated_session`
exists, and it is why this use case is shaped around **two transactions rather
than one**:

.. code-block:: text

    without_a_tenant()   -> the org row, and nothing else
    scoped_to(org_id)    -> roles, providers, the admin, the binding, the default

The narrowing is not decoration. ``SET LOCAL ROLE mnemos_admin`` holds
``BYPASSRLS``, so every statement issued under it is a statement tenant isolation
is not protecting. Keeping exactly one ``INSERT`` there means the other nine
statements are still checked by the policy — the admin user is inserted with the
GUC bound, so a bug that wrote the wrong ``org_id`` would be *rejected by
Postgres* rather than committed by a privileged session that was left open
because it was convenient.

**Two transactions is also why idempotency is not optional.** A crash between them
leaves an org with no admin, which under a "create once" design would be an
unrecoverable database. So every step is *create-if-absent*, and a second run
finishes whatever the first one started.

**Idempotency is create-if-absent, never update.** A second run adds what is
missing and changes nothing that exists — not the org name, not the admin's
password, not ``org.settings.default_provider``, not a role's grants. The reason
is that the operator hands this command a password: an "upsert" bootstrap wired
into a deploy script would silently reset the administrator's credential on every
release, and would silently revert a default-provider change made through the
app. The cost is that a change to :data:`~mnemos.features.identity.domain.roles.SYSTEM_ROLES`
does not reach an org that has already been bootstrapped; that is recorded in
TRACKER §4 rather than papered over here.

**Both provider rows are seeded, and the default is OIDC.** Without an
``identity_provider`` row nothing built in M3.2 or M3.3 can be exercised at all —
:class:`~mnemos.features.identity.providers.factory.ProviderFactory` reads that
table to decide which strategy to build, and an org with none denies every login.
Seeding only one would leave half the provider seam untestable by hand. The
default is the OIDC row because the browser-facing login for the shipped stack is
Keycloak; the internal password provider is reachable only by naming it, which
makes the seeded password a break-glass and CLI credential rather than the front
door.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from mnemos.core.errors import ValidationError
from mnemos.core.logging import get_logger
from mnemos.core.security import PasswordHasher
from mnemos.core.types import ProviderKind
from mnemos.features.identity.domain import (
    ADMIN_ROLE_SLUG,
    SYSTEM_ROLES,
    OrgId,
    ProviderId,
    RoleId,
    SystemRole,
    UserId,
)

logger = get_logger(__name__)

#: Slug and display name of the seeded password provider. ``internal`` matches
#: :data:`~mnemos.core.types.ProviderKind.INTERNAL` so the row reads the same way
#: in a `SELECT` as it does in the factory.
INTERNAL_PROVIDER_SLUG = "internal"
INTERNAL_PROVIDER_NAME = "Email and password"

#: Slug and display name of the seeded OIDC provider. Named for the IdP rather
#: than for the protocol, because an org may one day have two OIDC providers and
#: ``oidc`` would then be the one slug neither of them can have.
OIDC_PROVIDER_SLUG = "keycloak"
OIDC_PROVIDER_NAME = "Keycloak"

#: The bootstrap admin's password is a standing credential on a fresh system with
#: no rate limiting in front of it yet (M3.4 owns login attempts). 12 characters
#: is the floor OWASP's Authentication Cheat Sheet gives for a human-chosen
#: password and is the same number `docs/ThreatModel.md` §5 assumes when it argues
#: for argon2's memory cost. Anything shorter is refused here rather than accepted
#: and regretted, because there is no "change password" screen to fix it with.
MINIMUM_ADMIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class Ensured[T]:
    """A row's identifier, and whether *this run* is what created it.

    The flag is what makes the command's output honest: "created" and "already
    there" are different facts about the database, and a bootstrap that printed
    the same thing for both would make a second run indistinguishable from a
    first — which is precisely the question an operator runs it twice to answer.
    """

    id: T
    created: bool


@dataclass(frozen=True, slots=True)
class EnsuredOrg:
    """The org row as it now stands, which is not always as it was asked for.

    ``name`` is read back from the database rather than echoed from the request.
    A second run with a different ``--org-name`` does **not** rename the org — see
    the idempotency paragraph — and a report that printed the requested name would
    tell the operator a rename happened when it did not. The output of this
    command is the only feedback it gives, so it describes the database.
    """

    id: OrgId
    name: str
    created: bool


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """One ``identity_provider`` row, as the bootstrap wants it written.

    ``kind`` is a :class:`ProviderKind` here rather than the raw ``str`` the
    read-side :class:`~mnemos.features.identity.providers.ports.ProviderRecord`
    carries, and the asymmetry is deliberate: reading must survive a value this
    code does not recognise, writing must not be able to invent one.
    """

    slug: str
    kind: ProviderKind
    display_name: str
    is_enabled: bool = True
    issuer_public: str | None = None
    issuer_internal: str | None = None
    client_id: str | None = None


@dataclass(frozen=True, slots=True)
class OidcSettings:
    """What the seeded OIDC row needs to match the IdP that is actually running.

    Split horizon, again (ADAPTATION §8, M3.3): the browser is sent to
    ``issuer_public`` and the API discovers and validates against
    ``issuer_internal``. Seeding one URL into both columns is the failure that
    looks like it works from the host and denies every login from inside the
    compose network.
    """

    issuer_public: str
    issuer_internal: str
    client_id: str
    is_enabled: bool = True


@dataclass(frozen=True, slots=True)
class BootstrapRequest:
    """Everything the command needs, validated at construction.

    Validating here rather than in the CLI means the rules hold for any caller —
    a future admin API that provisions a second org cannot skip them by not
    knowing they exist.
    """

    org_slug: str
    org_name: str
    admin_email: str
    admin_display_name: str
    admin_password: str
    oidc: OidcSettings
    default_provider_slug: str

    def __post_init__(self) -> None:
        for field, value in (
            ("org_slug", self.org_slug),
            ("org_name", self.org_name),
            ("admin_email", self.admin_email),
            ("admin_display_name", self.admin_display_name),
        ):
            if not value.strip():
                raise ValidationError("bootstrap argument may not be blank", field=field)

        # `org.slug` is CITEXT and appears in URLs (`?org=<slug>`); a slug with a
        # space or a slash is one that has to be escaped at every call site, and
        # one of them will forget.
        if any(character.isspace() or character == "/" for character in self.org_slug):
            raise ValidationError(
                "org slug must not contain whitespace or '/'", field="org_slug", value=self.org_slug
            )

        if "@" not in self.admin_email:
            raise ValidationError("admin email must contain '@'", field="admin_email")

        # The password itself is never put in `details`: `ValidationError` is the
        # one error whose details cross the API boundary (core/errors.py), so a
        # value echoed here would be echoed to a client the day an admin API
        # calls this.
        if len(self.admin_password) < MINIMUM_ADMIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"admin password must be at least {MINIMUM_ADMIN_PASSWORD_LENGTH} characters",
                field="admin_password",
            )

        if self.default_provider_slug not in (INTERNAL_PROVIDER_SLUG, OIDC_PROVIDER_SLUG):
            raise ValidationError(
                "default provider must name one of the seeded providers",
                field="default_provider_slug",
                value=self.default_provider_slug,
            )

        # An org whose default provider is disabled denies every login that does
        # not name a provider explicitly — the factory's "no default and more than
        # one enabled" branch. Refusing to write that state is cheaper than
        # debugging it through a constant denial message.
        if self.default_provider_slug == OIDC_PROVIDER_SLUG and not self.oidc.is_enabled:
            raise ValidationError(
                "the default provider is disabled; enable OIDC or default to the internal provider",
                field="default_provider_slug",
            )

    def provider_specs(self) -> tuple[ProviderSpec, ...]:
        """Both rows, in the order they are written and reported."""
        return (
            ProviderSpec(
                slug=INTERNAL_PROVIDER_SLUG,
                kind=ProviderKind.INTERNAL,
                display_name=INTERNAL_PROVIDER_NAME,
            ),
            ProviderSpec(
                slug=OIDC_PROVIDER_SLUG,
                kind=ProviderKind.OIDC,
                display_name=OIDC_PROVIDER_NAME,
                is_enabled=self.oidc.is_enabled,
                issuer_public=self.oidc.issuer_public,
                issuer_internal=self.oidc.issuer_internal,
                client_id=self.oidc.client_id,
            ),
        )


class BootstrapWriter(Protocol):
    """The row writes, inside somebody else's transaction.

    Every method is ``ensure_*`` rather than ``create_*`` because the contract is
    create-if-absent: the caller must not have to ask "does this exist" and then
    race itself between the question and the answer.
    """

    async def ensure_org(self, *, slug: str, name: str) -> EnsuredOrg: ...

    async def ensure_role(self, *, org_id: OrgId, role: SystemRole) -> Ensured[RoleId]: ...

    async def ensure_provider(
        self, *, org_id: OrgId, spec: ProviderSpec
    ) -> Ensured[ProviderId]: ...

    async def ensure_user(
        self,
        *,
        org_id: OrgId,
        email: str,
        display_name: str,
        password_hash: str,
        provider_id: ProviderId,
    ) -> Ensured[UserId]: ...

    async def ensure_role_binding(
        self, *, org_id: OrgId, user_id: UserId, role_id: RoleId
    ) -> Ensured[uuid.UUID]: ...

    async def ensure_default_provider(self, *, org_id: OrgId, provider_slug: str) -> bool:
        """Write ``org.settings.default_provider`` **only if the key is absent**.

        Returns whether it wrote. An org that already names a default keeps it,
        even if it names a different provider than this run was asked for: that
        setting is the one thing here an operator plausibly changed on purpose
        after bootstrap, and silently reverting it is the failure mode of every
        "just re-run the seed script" deployment.
        """
        ...


class BootstrapStore(Protocol):
    """Hands out writers, one transaction at a time.

    The two methods exist so the *transaction boundary* and the privilege
    narrowing are visible in :meth:`Bootstrap.execute` rather than buried in an
    adapter (CodingStandards §6: transaction boundaries belong to the application
    layer). Reading the use case tells you exactly how much of it runs elevated.
    """

    def without_a_tenant(self) -> AbstractAsyncContextManager[BootstrapWriter]:
        """A transaction that escapes tenant isolation. Only the org row goes here."""
        ...

    def scoped_to(self, org_id: OrgId) -> AbstractAsyncContextManager[BootstrapWriter]:
        """An ordinary transaction with ``app.current_org`` bound. Everything else."""
        ...


@dataclass(frozen=True, slots=True)
class SeededRow:
    """One line of the command's report: what it is, and whether it is new."""

    label: str
    detail: str
    created: bool


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    """What the run did, in enough detail to sign in with and to audit.

    It carries the admin's **email** and the org **slug** because those two
    strings are the answer to "what do I log in with", and it carries no password
    and no hash because neither is ever a thing the operator needs printed back.

    Every field describes the database *after* the run, not the request that was
    made — so a second run's report is a true reading of what is there.
    """

    org_id: OrgId
    org_slug: str
    org_name: str
    org_created: bool
    admin_user_id: UserId
    admin_email: str
    admin_created: bool
    admin_role_slug: str
    role_binding_created: bool
    default_provider_slug: str
    default_provider_set: bool
    roles: tuple[SeededRow, ...]
    providers: tuple[SeededRow, ...]

    @property
    def created_anything(self) -> bool:
        return (
            self.org_created
            or self.admin_created
            or self.role_binding_created
            or self.default_provider_set
            or any(row.created for row in self.roles)
            or any(row.created for row in self.providers)
        )


class Bootstrap:
    """Create the first org and everything an operator needs to sign in to it."""

    def __init__(self, *, store: BootstrapStore, hasher: PasswordHasher) -> None:
        self._store = store
        self._hasher = hasher

    async def execute(self, request: BootstrapRequest) -> BootstrapReport:
        # Hashed before either transaction opens. Argon2id at this system's
        # parameters is 64 MiB of deliberate work (~50 ms); a transaction holding
        # a connection and a row lock is not where to spend it. The cost of
        # hashing a password a second run will not use is one run of the CLI.
        password_hash = await self._hasher.hash(request.admin_password)

        async with self._store.without_a_tenant() as writer:
            # The only statement in this command with no tenant to be scoped to.
            org = await writer.ensure_org(slug=request.org_slug, name=request.org_name)

        logger.info(
            "bootstrap.org_ensured",
            org_id=str(org.id),
            org_slug=request.org_slug,
            created=org.created,
        )

        # From here on the org exists, so the ordinary tenant-scoped session is
        # the correct tool and the elevated one would be an unnecessary hole.
        async with self._store.scoped_to(org.id) as writer:
            roles: dict[str, Ensured[RoleId]] = {}
            for system_role in SYSTEM_ROLES:
                roles[system_role.slug] = await writer.ensure_role(org_id=org.id, role=system_role)

            providers: dict[str, Ensured[ProviderId]] = {}
            for spec in request.provider_specs():
                providers[spec.slug] = await writer.ensure_provider(org_id=org.id, spec=spec)

            admin = await writer.ensure_user(
                org_id=org.id,
                email=request.admin_email,
                display_name=request.admin_display_name,
                password_hash=password_hash,
                # The account belongs to the password provider. Nothing in M3.2
                # reads this column to authenticate — the join would be one more
                # thing that can be wrong in the login path — but leaving it null
                # would make the admin indistinguishable from a user provisioned
                # by an IdP that has since been deleted.
                provider_id=providers[INTERNAL_PROVIDER_SLUG].id,
            )

            binding = await writer.ensure_role_binding(
                org_id=org.id, user_id=admin.id, role_id=roles[ADMIN_ROLE_SLUG].id
            )

            default_set = await writer.ensure_default_provider(
                org_id=org.id, provider_slug=request.default_provider_slug
            )

        report = BootstrapReport(
            org_id=org.id,
            org_slug=request.org_slug,
            # From the row, not from the request: a re-run does not rename.
            org_name=org.name,
            org_created=org.created,
            admin_user_id=admin.id,
            admin_email=request.admin_email,
            admin_created=admin.created,
            admin_role_slug=ADMIN_ROLE_SLUG,
            role_binding_created=binding.created,
            default_provider_slug=request.default_provider_slug,
            default_provider_set=default_set,
            roles=tuple(
                SeededRow(
                    label=system_role.slug,
                    detail=f"{len(system_role.grants)} grants",
                    created=roles[system_role.slug].created,
                )
                for system_role in SYSTEM_ROLES
            ),
            providers=tuple(
                SeededRow(
                    label=spec.slug,
                    detail=spec.kind.value if spec.is_enabled else f"{spec.kind.value} (disabled)",
                    created=providers[spec.slug].created,
                )
                for spec in request.provider_specs()
            ),
        )

        # No password, no hash, in the log or anywhere else (CodingStandards §8).
        logger.info(
            "bootstrap.completed",
            org_id=str(report.org_id),
            org_slug=report.org_slug,
            admin_email=report.admin_email,
            created_anything=report.created_anything,
        )
        return report
