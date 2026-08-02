"""Redis-backed storage for in-flight OIDC logins.

Two properties, and Redis is chosen for both.

**Single-use, atomically.** `take` uses `GETDEL` (Redis 6.2+), so read-and-delete
cannot interleave. A `GET` followed by a `DEL` has a window in which two concurrent
callbacks both read the same state and both succeed, which is exactly the replay
the state is there to prevent — and it is a window that only opens under the
concurrency an attacker can create deliberately.

**Expiring, and shared across replicas.** A dict on the app object would work on
one container and fail the moment `authorize` and `callback` land on different
replicas, or across a restart — a failure that looks like flaky login rather than
like the design error it is. The TTL means an abandoned attempt disappears on its
own rather than accumulating as a standing credential.

The stored value is a code verifier: a bearer secret for the duration of one
login. It is namespaced under `oidc:state:` and never logged.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from mnemos.features.identity.application.oidc_login import LoginState

KEY_PREFIX = "oidc:state:"


class RedisLoginStateStore:
    """`LoginStateStore` over Redis."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def put(self, state: str, value: LoginState, *, ttl_s: int) -> None:
        await self._client.set(
            KEY_PREFIX + state,
            json.dumps(
                {
                    "org_slug": value.org_slug,
                    "provider_slug": value.provider_slug,
                    "code_verifier": value.code_verifier,
                    "redirect_uri": value.redirect_uri,
                }
            ),
            ex=ttl_s,
        )

    async def take(self, state: str) -> LoginState | None:
        raw = await self._client.getdel(KEY_PREFIX + state)
        if raw is None:
            return None
        try:
            payload: Any = json.loads(raw)
            return LoginState(
                org_slug=payload["org_slug"],
                provider_slug=payload["provider_slug"],
                code_verifier=payload["code_verifier"],
                redirect_uri=payload["redirect_uri"],
            )
        except (ValueError, KeyError, TypeError):
            # A value we cannot parse is a value we cannot trust. The key is
            # already gone, so this is a denial rather than a poisoned retry.
            return None
