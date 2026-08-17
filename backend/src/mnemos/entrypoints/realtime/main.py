"""WebSocket gateway.

A separate container from the API because its scaling signal is connection
count, not request rate. A long-lived socket pins a worker; mixing those with
latency-sensitive HTTP means one noisy chat room degrades every request.

Fan-out goes through Redis pub/sub rather than process memory, so any API or
worker container can publish to a channel and every gateway replica delivers it.
In-process fan-out works precisely until there is more than one replica, which
is the point at which it is expensive to discover.

**Authenticated as of `B1` deliverable 3.** The handshake resolves the same
platform JWT the HTTP API does — through the same `PlatformTokenCodec` and
`PrincipalResolver`, reading the same `MNEMOS_JWT_SECRET` (`ThreatModel.md`
§5.1: api, worker and realtime are one trust domain) — and the channel a
caller subscribes to is always built from the token's own `org_id`, never from
the client-supplied `channel` path segment. A caller cannot reach another
org's channel by hand-typing its id into the URL, because that id is never
read from the URL at all.

The token travels as a `Sec-WebSocket-Protocol` offer, not a query parameter:
a browser cannot set an `Authorization` header on a WebSocket upgrade, and a
query string is the one place `core/config.py`'s `web_signin_complete_url`
already refuses to put a credential — it ends up in access logs, proxy logs
and browser history, and a subprotocol does not.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# Imported for its side effect on `Base.metadata`, same reason
# `entrypoints/api/main.py` imports it: `SqlPrincipalRepository`'s queries run
# against `AppUser`/`Org`/`Role`/`Session` specifically, but importing the full
# model surface here rather than trusting that subset is what keeps this
# process's mapper registry from depending on which other module happened to
# import first.
import mnemos.platform.models  # noqa: F401
from mnemos.core.clock import SYSTEM_CLOCK
from mnemos.core.config import get_settings
from mnemos.core.errors import AuthenticationError
from mnemos.core.ids import DEFAULT_ID_GENERATOR
from mnemos.core.logging import configure_logging, get_logger
from mnemos.features.identity.adapters.principals import SqlPrincipalRepository
from mnemos.features.identity.application.principals import AuthenticatedCaller, PrincipalResolver
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.platform.cache import Cache
from mnemos.platform.db import Database

log = get_logger(__name__)

HEARTBEAT_INTERVAL_S = 20

#: The one subprotocol this gateway understands. The client offers exactly
#: two subprotocol values, in order — this constant, then the access token —
#: and the server echoes only this one back, never the token, so the token
#: does not appear a second time in a response header either.
BEARER_SUBPROTOCOL: Final = "bearer"

#: The only channel kinds a caller may subscribe to. `ingestion` is the one
#: `B1` deliverable 4's worker publishes to
#: (`mnemos:org:{org_id}:ingestion`); a kind outside this set is refused
#: before it can become part of a topic string, the same closed-set discipline
#: `entrypoints/api/security.py`'s public-path allow-list uses.
ALLOWED_CHANNEL_KINDS: Final[frozenset[str]] = frozenset({"ingestion"})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(
        json_output=not settings.is_local, session_log_enabled=settings.session_log_enabled
    )
    app.state.db = Database(settings)
    app.state.cache = Cache(settings)

    # The identical codec construction `entrypoints/api/main.py` builds from
    # the same `Settings` fields — one signing secret, one issuer, one
    # algorithm allow-list, so a token the API minted is a token this gateway
    # accepts and nothing here can drift into verifying against a different
    # one.
    codec = PlatformTokenCodec(
        config=PlatformTokenConfig(
            secret=settings.jwt_secret.get_secret_value(),
            issuer=settings.jwt_issuer,
            algorithm=settings.jwt_algorithm,
            access_ttl_s=settings.access_token_ttl_s,
            min_secret_length=settings.jwt_min_secret_length,
        ),
        clock=SYSTEM_CLOCK,
        ids=DEFAULT_ID_GENERATOR,
    )
    app.state.principals = PrincipalResolver(
        codec=codec,
        repository=SqlPrincipalRepository(app.state.db),
        clock=SYSTEM_CLOCK,
    )

    log.info("realtime.startup")
    try:
        yield
    finally:
        await app.state.cache.close()
        await app.state.db.dispose()
        log.info("realtime.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="Mnemos Realtime", version="0.3.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws/{channel}")
    async def subscribe(websocket: WebSocket, channel: str) -> None:
        """Subscribe to one org-scoped channel and forward everything published to it.

        Two denials, one code and no reason on the wire: a caller that offered
        no valid token and a caller that named an unknown channel kind both
        see the handshake refused the same way. Distinguishing them would be
        an oracle a client could probe with (`ThreatModel.md` §3, the identity
        layer's "every denial reads the same" discipline, applied here too).
        """
        caller = await _authenticate(websocket)
        if caller is None:
            return
        if channel not in ALLOWED_CHANNEL_KINDS:
            await websocket.close(code=1008)
            return

        org_id = caller.principal.org_id
        topic = f"mnemos:org:{org_id}:{channel}"

        await websocket.accept(subprotocol=BEARER_SUBPROTOCOL)
        cache: Cache = websocket.app.state.cache
        pubsub = cache.client.pubsub()

        await pubsub.subscribe(topic)
        await websocket.send_json({"type": "subscribed", "channel": channel})
        log.info("realtime.subscribed", channel=channel, org_id=str(org_id))

        async def pump() -> None:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data = message["data"]
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    payload = {"type": "message", "data": data}
                await websocket.send_json(payload)

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                # Client frames are drained so a disconnect is noticed promptly;
                # inbound commands (typing, cancel) arrive here from M8.
                raw = await websocket.receive_text()
                if raw == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            log.info("realtime.disconnected", channel=channel, org_id=str(org_id))
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task
            await pubsub.unsubscribe(topic)
            # redis-py's PubSub.aclose is not itself annotated, so strict mypy sees an
            # untyped call here even though every argument and the return path are
            # fine; the gap is in the dependency, not this code.
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    return app


async def _authenticate(websocket: WebSocket) -> AuthenticatedCaller | None:
    """Resolve the caller from the token offered as a WS subprotocol, or deny.

    Runs, and can close the socket, before `accept()` — a rejected handshake
    never becomes an open connection a caller could otherwise probe over.
    """
    raw_subprotocols = websocket.scope.get("subprotocols")
    offered: list[str] = raw_subprotocols if isinstance(raw_subprotocols, list) else []
    if len(offered) != 2 or offered[0] != BEARER_SUBPROTOCOL:
        await websocket.close(code=1008)
        return None

    resolver: PrincipalResolver = websocket.app.state.principals
    try:
        return await resolver.resolve(offered[1])
    except AuthenticationError:
        await websocket.close(code=1008)
        return None


app = create_app()
