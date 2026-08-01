"""The factory: an ``identity_provider`` row in, a strategy out.

This is the composition root for authentication. It is the only place that maps a
stored ``kind`` to a class, which is what makes adding SAML later a row plus an
adapter plus one branch here, rather than an edit to the login endpoint. The
endpoint (M3.3) asks for a strategy and calls it; it never learns which one it got.

**Deny by default, everywhere.** Unknown org, inactive org, unknown provider slug,
disabled provider, unrecognised ``kind``, a provider whose configuration is
incomplete, an ambiguous default — every one of them raises the same
:data:`~.base.AUTHENTICATION_FAILED`, with the real reason in the log. A factory
that raises ``KeyError`` on an unknown kind returns a 500 with a stack trace and
tells the caller which orgs and providers exist.

**The credential names its tenant.** ``app_user``, ``session``, ``api_key`` and
``identity_provider`` are all org-scoped and all under RLS, so nothing about a
caller is readable until an org is known: a bare bearer token identifies nobody.
The alternative to carrying the tenant in the credential is ``BYPASSRLS`` in the
authenticated request path, which would undo the M3 prerequisite. So the org slug
is a required argument here.

**And that costs no elevation.** ``org`` is the one table without RLS — it is what
the policies compare against — so resolving a slug to an org id needs no special
privilege, and every read after it happens with the GUC set to the org just
resolved. ``Database.elevated_session()`` keeps its single bootstrap call site;
the authentication path never touches it.
"""

from __future__ import annotations

from mnemos.core.logging import get_logger
from mnemos.core.security import PasswordHasher
from mnemos.core.types import ProviderKind
from mnemos.features.identity.domain import OrgId
from mnemos.features.identity.providers.base import AuthProvider, denied
from mnemos.features.identity.providers.internal import InternalProvider
from mnemos.features.identity.providers.oidc import JwksSource, OidcConfig, OidcProvider
from mnemos.features.identity.providers.ports import (
    OrgDirectory,
    ProviderRecord,
    UserDirectory,
)

logger = get_logger(__name__)


class ProviderFactory:
    """Builds the authentication strategy configured for an org."""

    def __init__(
        self,
        *,
        orgs: OrgDirectory,
        users: UserDirectory,
        hasher: PasswordHasher,
        jwks: JwksSource,
    ) -> None:
        self._orgs = orgs
        self._users = users
        self._hasher = hasher
        self._jwks = jwks

    async def for_org(self, org_slug: str, provider_slug: str | None = None) -> AuthProvider:
        """Resolve ``org_slug`` (+ optional ``provider_slug``) to a strategy.

        Raises the standard denial for every failure, including "no such org" —
        the caller is unauthenticated, and telling it which orgs exist is a free
        tenant enumeration.
        """
        org = await self._orgs.find_org(org_slug.strip())
        if org is None:
            raise denied(f"no org with slug {org_slug!r}")
        if not org.is_active:
            raise denied(f"org {org_slug!r} is not active")

        record = await self._resolve_provider(
            org.org_id, provider_slug or org.default_provider_slug
        )
        if not record.is_enabled:
            raise denied(f"provider {record.slug!r} is disabled for org {org_slug!r}")

        return self._build(record)

    async def _resolve_provider(self, org_id: OrgId, slug: str | None) -> ProviderRecord:
        if slug is not None:
            record = await self._orgs.find_provider(org_id, slug.strip())
            if record is None:
                raise denied(f"no provider {slug!r} for org {org_id}")
            return record

        # No slug asked for and no default configured. One enabled provider is
        # unambiguous; anything else is a guess, and guessing which login method
        # an org meant is how a stronger provider gets silently bypassed for a
        # weaker one that happens to sort first.
        enabled = await self._orgs.list_enabled_providers(org_id)
        if len(enabled) != 1:
            raise denied(
                f"org {org_id} has {len(enabled)} enabled providers and no default; "
                "the credential must name one"
            )
        return enabled[0]

    def _build(self, record: ProviderRecord) -> AuthProvider:
        # `kind` is a raw string from the database on purpose (see ports.py): an
        # unrecognised value must deny, not raise out of an enum constructor.
        try:
            kind = ProviderKind(record.kind)
        except ValueError:
            raise denied(f"provider {record.slug!r} has unknown kind {record.kind!r}") from None

        if kind is ProviderKind.INTERNAL:
            return InternalProvider(
                provider_id=record.provider_id,
                org_id=record.org_id,
                users=self._users,
                hasher=self._hasher,
            )
        if kind is ProviderKind.OIDC:
            return self._build_oidc(record)

        # `ProviderKind.API_KEY` reaches here. API keys are machine credentials
        # authenticated against `api_key` (M3.5), not a login strategy, and a row
        # claiming otherwise is a misconfiguration rather than a new capability.
        raise denied(f"provider kind {kind.value!r} is not a login strategy")

    def _build_oidc(self, record: ProviderRecord) -> OidcProvider:
        # Incomplete OIDC configuration is a denial, not a set of `None`s carried
        # into the validator to fail some other way later. Without an issuer there
        # is nothing to trust; without a client id the audience check — the one
        # that stops a token minted for another client — cannot run at all.
        if not record.issuer_internal:
            raise denied(f"OIDC provider {record.slug!r} has no internal issuer configured")
        if not record.client_id:
            raise denied(f"OIDC provider {record.slug!r} has no client id configured")
        return OidcProvider(
            provider_id=record.provider_id,
            org_id=record.org_id,
            config=OidcConfig.build(
                issuer_internal=record.issuer_internal,
                issuer_public=record.issuer_public,
                client_id=record.client_id,
            ),
            jwks=self._jwks,
        )
