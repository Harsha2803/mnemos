"""Redis Streams — the `EventBus` adapter.

Chosen over `platform/cache.py`'s pub/sub deliberately (ADAPTATION §3, §9,
locked decision — not a choice to re-litigate). `entrypoints/realtime/main.py`
(deliverable 3) does not read from this adapter directly: `B1`'s own dated
note in TRACKER records the two live options for getting a Streams entry to a
browser — (a) the worker publishes to this stream *and* to the existing
pub/sub channel the gateway already relays, or (b) the gateway itself runs a
consumer-group reader per subscription — and takes (a), so the gateway needs
no new code for `B1`. Reading this stream from a WebSocket's last-seen id
(replay on reconnect) is real `B2` depth, deliberately not built here.

`ensure_group` starts a new group at id `"0"`, not `"$"`: a group created
against a stream that already has entries should see the backlog on its first
`read_group`, not just what arrives after it was created — that backlog *is*
the durability this adapter exists to provide over pub/sub.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.typing import EncodableT, FieldT

from mnemos.core.errors import DependencyUnavailableError, UpstreamError
from mnemos.platform.events.port import StreamMessage

# XREADGROUP's runtime shape under RESP2 (redis-py's default protocol, and the
# one `Cache` connects with — see `redis/_parsers/response_callbacks.py`'s
# `parse_xread`): `list[[stream_name, [(entry_id, fields), ...]]]`. The
# type stubs also allow a RESP3 dict shape that this client never produces;
# the cast below is scoped to that one, deliberate gap between what the
# stubs allow and what this adapter's connection actually sends back.
_XReadGroupEntries = list[tuple[str, list[tuple[str, dict[str, str]]]]]


class RedisStreamsEventBus:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def publish(self, stream: str, fields: Mapping[str, str]) -> str:
        # redis-py's `xadd` takes the invariant `Dict[FieldT, EncodableT]`,
        # not `Mapping[str, str]`; the values really are `str` at runtime
        # (every caller passes string fields), so this is a type-only cast,
        # not a behaviour change.
        payload = cast(dict[FieldT, EncodableT], dict(fields))
        try:
            message_id = await self._client.xadd(stream, payload)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DependencyUnavailableError("event bus is unreachable", reason=str(exc)) from exc
        except RedisError as exc:
            raise UpstreamError("event bus rejected the publish", reason=str(exc)) from exc
        return str(message_id)

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._client.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            # BUSYGROUP: the group already exists. Idempotent by design — a
            # worker restart must be able to call this every time it starts,
            # not just the first time the group is ever created.
            if "BUSYGROUP" not in str(exc):
                raise UpstreamError(
                    "event bus rejected the group creation", reason=str(exc)
                ) from exc
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DependencyUnavailableError("event bus is unreachable", reason=str(exc)) from exc

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 5000,
    ) -> Sequence[StreamMessage]:
        try:
            raw = await self._client.xreadgroup(
                group, consumer, {stream: ">"}, count=count, block=block_ms
            )
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DependencyUnavailableError("event bus is unreachable", reason=str(exc)) from exc
        except RedisError as exc:
            raise UpstreamError("event bus rejected the read", reason=str(exc)) from exc

        if not raw:
            return []

        entries = cast(_XReadGroupEntries, raw)
        return [
            StreamMessage(id=entry_id, fields=fields)
            for _stream_name, records in entries
            for entry_id, fields in records
        ]

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        try:
            await self._client.xack(stream, group, message_id)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DependencyUnavailableError("event bus is unreachable", reason=str(exc)) from exc
        except RedisError as exc:
            raise UpstreamError("event bus rejected the ack", reason=str(exc)) from exc
