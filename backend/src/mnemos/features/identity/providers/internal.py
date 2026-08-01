"""Internal authentication: a password verified against ``app_user.password_hash``.

The simplest strategy, and the one where the mistakes are quiet ones. Three
properties are load-bearing and each has a test:

*A user with no password hash cannot password-authenticate.* ``password_hash`` is
nullable because a user provisioned from Keycloak has no local password. Treating
``NULL`` as "no password required" rather than "this login method is unavailable
to this user" would turn every external user into an unauthenticated account.

*Every failure path costs the same.* Unknown org, unknown email, deactivated user,
absent hash and wrong password all run a full argon2 verification before denying —
:meth:`PasswordHasher.verify` does it for the ``None`` case. Otherwise the
response time distinguishes "no such user" (microseconds) from "wrong password"
(tens of milliseconds), and an attacker enumerates the org's users without ever
reading an error message.

*The hash is upgraded on the one occasion the plaintext exists.* When argon2's
cost parameters are raised, existing hashes are still valid but weaker.
:attr:`InternalProvider.rehash_required` reports that a successful login should be
followed by a re-hash; the write is the application layer's, since this layer is
read-only by design.
"""

from __future__ import annotations

from mnemos.core.security import PasswordHasher
from mnemos.core.types import ProviderKind
from mnemos.features.identity.domain import OrgId, ProviderId
from mnemos.features.identity.providers.base import AuthenticatedSubject, denied
from mnemos.features.identity.providers.ports import UserDirectory


class InternalProvider:
    """Password authentication against the local user table, for one org."""

    def __init__(
        self,
        *,
        provider_id: ProviderId,
        org_id: OrgId,
        users: UserDirectory,
        hasher: PasswordHasher,
    ) -> None:
        self._provider_id = provider_id
        self._org_id = org_id
        self._users = users
        self._hasher = hasher
        self._rehash_required = False

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.INTERNAL

    @property
    def provider_id(self) -> ProviderId:
        return self._provider_id

    @property
    def rehash_required(self) -> bool:
        """True when the last successful verification used out-of-date parameters.

        Read by the caller immediately after a successful ``authenticate``; it
        says nothing after a denial and is not a property of the provider between
        calls.
        """
        return self._rehash_required

    async def authenticate(self, *, email: str, password: str) -> AuthenticatedSubject:
        self._rehash_required = False
        record = await self._users.find_by_email(self._org_id, email.strip())

        # One branch, one denial. Splitting these into distinct messages or
        # distinct early returns is exactly how the timing and wording differences
        # that leak user existence get reintroduced.
        if record is None or not record.is_active or record.password_hash is None:
            await self._hasher.verify(None, password)
            reason = (
                "no such user"
                if record is None
                else "user is inactive"
                if not record.is_active
                else "user has no password hash (external identity only)"
            )
            raise denied(reason)

        if not await self._hasher.verify(record.password_hash, password):
            raise denied("password mismatch")

        self._rehash_required = self._hasher.needs_rehash(record.password_hash)
        return AuthenticatedSubject(
            org_id=record.org_id,
            provider_id=self._provider_id,
            provider_kind=ProviderKind.INTERNAL,
            user_id=record.user_id,
            email=record.email,
            display_name=record.display_name,
        )
