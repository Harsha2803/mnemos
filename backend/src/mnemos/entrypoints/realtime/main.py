"""WebSocket gateway.

A separate container from the API because its scaling signal is connection
count, not request rate. A long-lived socket pins a worker; mixing those with
latency-sensitive HTTP means one noisy chat room degrades every request.

Fan-out goes through Redis pub/sub rather than process memory, so any API or
worker container can publish to a channel and every gateway replica delivers it.
In-process fan-out works precisely until there is more than one replica, which
is the point at which it is expensive to discover.

Authentication lands in M3; until then the gateway is bound to the compose
network and not exposed to the internet.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from mnemos.core.config import get_settings
from mnemos.core.logging import configure_logging, get_logger
from mnemos.platform.cache import Cache

log = get_logger(__name__)

HEARTBEAT_INTERVAL_S = 20


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(json_output=not settings.is_local)
    app.state.cache = Cache(settings)
    log.info("realtime.startup")
    try:
        yield
    finally:
        await app.state.cache.close()
        log.info("realtime.shutdown")


app = FastAPI(title="Mnemos Realtime", version="0.2.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/{channel}")
async def subscribe(websocket: WebSocket, channel: str) -> None:
    """Subscribe to one channel and forward everything published to it."""
    await websocket.accept()
    cache: Cache = websocket.app.state.cache
    pubsub = cache.client.pubsub()
    topic = f"mnemos:{channel}"

    await pubsub.subscribe(topic)
    await websocket.send_json({"type": "subscribed", "channel": channel})
    log.info("realtime.subscribed", channel=channel)

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
        log.info("realtime.disconnected", channel=channel)
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        await pubsub.unsubscribe(topic)
        await pubsub.aclose()
