"""The route guard. **Authenticated by default; public by enumeration.**

The dependency below is installed on the application itself, not on individual
routes:

.. code-block:: python

    FastAPI(dependencies=[Depends(enforce_authentication)])

FastAPI merges application-level dependencies into every route it registers,
including routers included later and routes added after startup. So a route that
declares nothing is a route that is *guarded*, and forgetting to protect a new
endpoint is not a thing that can happen. The opposite arrangement — a
``@requires_auth`` a developer remembers to write — fails open exactly once, on
the endpoint nobody reviewed.

**The public list is exact paths and nothing else.** No prefix, no regex, no
``startswith``. A prefix match is one careless route name away from exposing
everything beneath it: ``/api/v1/auth`` as a prefix makes a future
``/api/v1/auth/users`` public, and nobody adding that route would think to check
the allow-list. Set membership on the literal path has no such failure mode, and
its edge cases all fall the safe way — ``/healthz/``, ``//healthz`` and
``/healthz%20`` are all simply *not in the set*, and are denied.

**Nothing here decides what a caller may do.** The guard answers "who is this",
puts an :class:`AuthenticatedCaller` on ``request.state``, and stops. The
permission matrix — ``require_permission(...)`` over ``PermissionSet`` — is a
later milestone, and building half of it now would mean shipping a check nothing
requires and nothing tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import Token
from typing import Final

from fastapi import Request

from mnemos.core.logging import org_id_var, session_id_var, user_id_var
from mnemos.features.identity.application.principals import (
    AuthenticatedCaller,
    PrincipalResolver,
)
from mnemos.features.identity.providers import denied

#: What `bind_caller_context` hands back to `reset_caller_context` — one
#: `contextvars.Token` per var it set, in the same order.
CallerContextTokens = tuple[Token[str | None], Token[str | None], Token[str | None]]

#: The scheme, compared case-insensitively per RFC 7235 §2.1.
BEARER_SCHEME: Final = "bearer"

#: Paths FastAPI serves that are not ``APIRoute``s — the docs UI and the schema.
#: They carry no dependencies at all, so the guard cannot reach them however it
#: is installed. Enumerating them anyway is what makes the allow-list a complete
#: statement of what is public rather than a partial one, and
#: ``test_every_route_the_guard_cannot_reach_is_named_in_the_allowlist`` fails if
#: a future FastAPI adds a fifth.
DOCUMENTATION_PATHS: Final[frozenset[str]] = frozenset(
    {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
)


def public_route_paths(api_prefix: str) -> frozenset[str]:
    """Every path reachable without a credential, as exact strings.

    The auth routes are here because they are how a caller *obtains* a
    credential: requiring one to reach them is a system nobody can sign in to.
    They are individually named — ``/auth/me`` is deliberately absent and is
    therefore guarded, which is exactly the property a prefix would have thrown
    away.

    ``/healthz`` and ``/readyz`` are public because an orchestrator's probe has
    no credential and must never need one; ``/`` because a service that will not
    say its own name to an unauthenticated caller is a service nobody can
    diagnose. None of the three read a row.
    """
    auth = f"{api_prefix}/auth"
    return DOCUMENTATION_PATHS | frozenset(
        {
            "/",
            "/healthz",
            "/readyz",
            f"{auth}/oidc/authorize",
            f"{auth}/oidc/callback",
            f"{auth}/token",
            f"{auth}/token:revoke",
        }
    )


def bearer_token(request: Request) -> str:
    """Pull the access token out of ``Authorization``, or deny.

    Deliberately not FastAPI's ``HTTPBearer``: that returns a 403 with
    ``{"detail": "Not authenticated"}``, which is both the wrong status and a
    second error shape competing with the one the API has (`CodingStandards` §4).
    Everything here raises the same ``AuthenticationError`` the identity layer
    raises, so one handler renders every denial in the system.
    """
    header = request.headers.get("authorization")
    if not header:
        raise denied("request carried no Authorization header")
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != BEARER_SCHEME or not token.strip():
        raise denied(f"Authorization header is not a bearer token: scheme={scheme!r}")
    return token.strip()


def bind_caller_context(caller: AuthenticatedCaller) -> CallerContextTokens:
    """Bind `caller`'s org/user/session ids to `core/logging.py`'s contextvars.

    Two call sites need this, not one: :func:`enforce_authentication` below,
    for log lines the route handler itself emits, and `main.py`'s
    request-logging middleware, for the `http.request` summary line — which is
    emitted *after* `call_next` returns, by which point this dependency's own
    binding has already been reset (dependency teardown runs inside
    `call_next`, before control returns to the middleware). Sharing this
    function is what keeps both bindings — and both resets — identical.
    """
    return (
        org_id_var.set(str(caller.principal.org_id)),
        user_id_var.set(str(caller.principal.principal_id)),
        session_id_var.set(str(caller.principal.session_id)),
    )


def reset_caller_context(tokens: CallerContextTokens) -> None:
    org_token, user_token, session_token = tokens
    org_id_var.reset(org_token)
    user_id_var.reset(user_token)
    session_id_var.reset(session_token)


async def enforce_authentication(request: Request) -> AsyncIterator[None]:
    """The application-level dependency. Runs before every route handler.

    Stores the resolved caller on ``request.state`` rather than returning it,
    because a dependency's return value is only reachable by a handler that
    declared it — and a handler that forgot to declare it must still be guarded.
    :func:`require_caller` is how a handler that *wants* the identity asks for it.

    A generator rather than a plain coroutine so the caller's org/user/session
    ids can be bound to `core/logging.py`'s contextvars *and reset* once the
    route handler is done — the ``finally`` below is what keeps one request's
    identity from bleeding into whatever this task does next. Denial is
    unaffected: an exception raised while resolving the caller propagates
    before the ``yield`` the same way a ``return`` did in the
    plain-coroutine version.
    """
    if request.url.path in _public_paths(request):
        yield
        return

    caller = await _resolver(request).resolve(bearer_token(request))
    request.state.caller = caller
    tokens = bind_caller_context(caller)
    try:
        yield
    finally:
        reset_caller_context(tokens)


def require_caller(request: Request) -> AuthenticatedCaller:
    """The resolved caller, for a handler that needs to know who is asking.

    Raises rather than returning ``None`` if the guard did not run: that can only
    mean the handler is on a public path and is asking for an identity nobody
    presented, which is a programming error and not a request to deny.
    """
    caller = getattr(request.state, "caller", None)
    if not isinstance(caller, AuthenticatedCaller):  # pragma: no cover - see docstring
        msg = f"{request.url.path} asked for a caller but is not behind the guard"
        raise RuntimeError(msg)
    return caller


def _public_paths(request: Request) -> frozenset[str]:
    paths = getattr(request.app.state, "public_route_paths", None)
    if not isinstance(paths, frozenset):  # pragma: no cover - create_app sets it
        msg = "the public route allow-list is not configured"
        raise RuntimeError(msg)
    return paths


def _resolver(request: Request) -> PrincipalResolver:
    """Built once, in the lifespan, and shared — like the OIDC flow beside it.

    Absent means the process is misconfigured, not that the caller is
    unauthorized, so this is a 500 and not a denial. A guard that silently let
    requests through when its resolver was missing would be a guard that fails
    open on a deployment mistake.
    """
    resolver = getattr(request.app.state, "principals", None)
    if not isinstance(resolver, PrincipalResolver):  # pragma: no cover - the lifespan sets it
        msg = "the principal resolver is not configured"
        raise RuntimeError(msg)
    return resolver
