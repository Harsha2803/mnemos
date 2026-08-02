"""Password and secret hashing.

This lives in ``core`` rather than in ``features/identity/providers`` because two
different things hash a low-entropy secret with it: internal password auth (M3.2)
and API-key secrets (M3.5). One hasher, one set of parameters, one place to raise
them when hardware gets faster.

Three decisions worth naming, because each is the kind that gets "simplified" by a
later reader who does not know why it is there:

*Argon2id, never bcrypt and never a bare digest.* Passwords are low-entropy, so
the only defence against an offline attack on a stolen hash is to make each guess
expensive in **memory** as well as time. Parameters follow OWASP's current
guidance (m=64 MiB, t=3, p=4) and match `docs/ThreatModel.md` §5.

*Hashing runs in a worker thread.* Argon2 is deliberately CPU- and memory-bound;
64 MiB of mixing takes tens of milliseconds. Called inline from an async handler
that would freeze the event loop for **every** concurrent request, which is how a
login endpoint becomes a self-inflicted denial of service (CodingStandards §3).

*A failed lookup still pays for a verification.* :meth:`PasswordHasher.verify`
accepts ``None`` for the stored hash and verifies against a throwaway hash before
returning ``False``. Without that, "no such user" returns in microseconds while
"wrong password" takes 60 ms, and the difference is a user-enumeration oracle that
needs no error message to read.

High-entropy secrets are a different problem and deliberately do **not** use this:
a 256-bit random refresh token has no dictionary to slow down, and argon2's
per-row salt would make the hash column unsearchable. Those hash with SHA-256 —
see :func:`digest_token`.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Final

import anyio.to_thread
from argon2 import PasswordHasher as _Argon2Hasher
from argon2 import Type as _Argon2Type
from argon2.exceptions import Argon2Error, InvalidHashError, VerificationError

# OWASP guidance for Argon2id, mirrored in `docs/ThreatModel.md` §5. Memory is in
# KiB, which is the one unit in this file worth reading twice.
ARGON2_MEMORY_COST_KIB: Final = 64 * 1024
ARGON2_TIME_COST: Final = 3
ARGON2_PARALLELISM: Final = 4
ARGON2_HASH_LEN: Final = 32
ARGON2_SALT_LEN: Final = 16

# Verified against when there is no stored hash, so the miss path costs what the
# hit path costs. The plaintext is irrelevant — nothing can present it, because
# nothing is ever given it.
_ABSENT_SECRET: Final = "there-is-no-password-for-this-subject"


class PasswordHasher:
    """Argon2id hashing for low-entropy secrets: passwords and API-key secrets.

    Stateless apart from the lazily built dummy hash, so one instance is shared by
    the whole process and constructed at the composition root.
    """

    def __init__(
        self,
        *,
        memory_cost_kib: int = ARGON2_MEMORY_COST_KIB,
        time_cost: int = ARGON2_TIME_COST,
        parallelism: int = ARGON2_PARALLELISM,
    ) -> None:
        self._hasher = _Argon2Hasher(
            memory_cost=memory_cost_kib,
            time_cost=time_cost,
            parallelism=parallelism,
            hash_len=ARGON2_HASH_LEN,
            salt_len=ARGON2_SALT_LEN,
            type=_Argon2Type.ID,
        )
        self._absent_hash: str | None = None

    async def hash(self, secret: str) -> str:
        """Hash a secret. The salt and the parameters are encoded in the result,
        so a future parameter change does not invalidate existing hashes."""
        return await anyio.to_thread.run_sync(self._hasher.hash, secret)

    async def verify(self, stored_hash: str | None, secret: str) -> bool:
        """Check a secret against a stored hash.

        ``stored_hash=None`` means the subject has no password at all — an
        external-IdP-only user, or no user by that address. It still performs a
        verification against a dummy hash so the two outcomes take the same time,
        then returns ``False``.

        Returns a bool rather than raising: a wrong password is an ordinary
        outcome of a legitimate request, and the *caller* decides what a denial
        looks like on the wire (CodingStandards §4). A corrupt hash in the
        database is treated as a denial too, not a 500 — it must not be possible
        to break authentication for everyone by writing one bad row.
        """
        if stored_hash is None:
            await self._burn_time(secret)
            return False
        try:
            return await anyio.to_thread.run_sync(self._verify_sync, stored_hash, secret)
        except (VerificationError, InvalidHashError, Argon2Error):
            return False

    def _verify_sync(self, stored_hash: str, secret: str) -> bool:
        # argon2-cffi signals a mismatch by raising; `verify` only ever returns
        # True. The raise is translated in `verify`, which is the only caller.
        return bool(self._hasher.verify(stored_hash, secret))

    async def _burn_time(self, secret: str) -> None:
        """Spend a verification's worth of work on a subject that has no hash."""
        if self._absent_hash is None:
            self._absent_hash = await self.hash(_ABSENT_SECRET)
        try:
            await anyio.to_thread.run_sync(self._verify_sync, self._absent_hash, secret)
        except (VerificationError, InvalidHashError, Argon2Error):
            return

    def needs_rehash(self, stored_hash: str) -> bool:
        """True when the hash was made with weaker parameters than current policy.

        The caller re-hashes on the next successful login, which is the only
        moment the plaintext exists. A hash that cannot be parsed at all is not
        "needs rehash" — it is a denial, already handled in :meth:`verify`.
        """
        try:
            return self._hasher.check_needs_rehash(stored_hash)
        except InvalidHashError:
            return False


def digest_token(token: str) -> str:
    """SHA-256 hex digest, for **high-entropy** secrets only: refresh tokens.

    Deliberately not argon2, and the reason is the first question a reviewer asks.
    ``uq_session_refresh_token_hash`` is a unique index, and lookup is by hash — a
    per-row salt would make the column unsearchable without scanning every session
    row and verifying each one. That is affordable only because the input is a
    256-bit random string: there is no dictionary to slow down, so the work factor
    argon2 buys would defend against an attack that cannot be mounted. Argon2id
    stays where the entropy is low (passwords, API-key secrets), which is where it
    earns its cost.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(left: str, right: str) -> bool:
    """Constant-time comparison, for comparing digests and key prefixes.

    ``==`` on a string short-circuits at the first differing byte, which leaks the
    length of the matching prefix to anything that can time it.
    """
    return hmac.compare_digest(left, right)
