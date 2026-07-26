"""Redis: cache, distributed locks, and (from M5) the Streams event bus."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from mnemos.core.config import Settings
from mnemos.core.errors import ConflictError


class Cache:
    def __init__(self, settings: Settings) -> None:
        self._client: Redis = Redis.from_url(
            settings.redis_url, decode_responses=True, health_check_interval=30
        )

    @property
    def client(self) -> Redis:
        return self._client

    async def ping(self) -> None:
        await self._client.ping()

    @asynccontextmanager
    async def lock(self, key: str, *, ttl_s: int = 60) -> AsyncIterator[None]:
        """Single-owner lock.

        The TTL is not optional: a worker that dies holding a lock must not wedge
        the queue until someone notices. This is the lesson that shows up as
        stuck-job detection in the ingestion pipeline.
        """
        token = await self._client.set(f"lock:{key}", "1", nx=True, ex=ttl_s)
        if not token:
            raise ConflictError("lock is held by another owner", key=key)
        try:
            yield
        finally:
            await self._client.delete(f"lock:{key}")

    async def close(self) -> None:
        await self._client.aclose()
