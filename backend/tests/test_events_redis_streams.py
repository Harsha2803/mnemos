"""`RedisStreamsEventBus` — proved against a real Redis (the `redis_url`
fixture), not a fake, because the property this adapter exists for —
durability across a consumer group, not merely fan-out — is Redis Streams'
own guarantee, not something a fake pub/sub substitute could demonstrate."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from mnemos.core.errors import DependencyUnavailableError
from mnemos.platform.events.redis_streams import RedisStreamsEventBus


@pytest.fixture
async def bus(redis_url: str) -> RedisStreamsEventBus:
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    return RedisStreamsEventBus(client)


def _stream() -> str:
    # A fresh stream name per test so tests never see each other's entries,
    # without needing a real Redis `FLUSHALL` between them.
    return f"test:events:{uuid.uuid4()}"


async def test_publish_then_read_group_delivers_the_fields(bus: RedisStreamsEventBus) -> None:
    stream = _stream()
    await bus.ensure_group(stream, "workers")

    await bus.publish(stream, {"job_id": "abc", "to_status": "running"})

    messages = await bus.read_group(stream, "workers", "consumer-1", block_ms=100)

    assert len(messages) == 1
    assert messages[0].fields == {"job_id": "abc", "to_status": "running"}
    assert messages[0].id  # a real Streams-assigned id, not empty


async def test_ensure_group_sees_entries_published_before_the_group_existed(
    bus: RedisStreamsEventBus,
) -> None:
    """A group starts at id `"0"`, not `"$"` — the backlog is the whole point
    of using Streams over pub/sub, so a group created late must still see it."""
    stream = _stream()

    await bus.publish(stream, {"job_id": "before-group"})
    await bus.ensure_group(stream, "workers")

    messages = await bus.read_group(stream, "workers", "consumer-1", block_ms=100)

    assert [m.fields["job_id"] for m in messages] == ["before-group"]


async def test_ensure_group_is_idempotent(bus: RedisStreamsEventBus) -> None:
    stream = _stream()
    await bus.ensure_group(stream, "workers")

    # A second call (a worker restarting) must not raise BUSYGROUP.
    await bus.ensure_group(stream, "workers")


async def test_unacked_message_is_not_redelivered_to_the_same_consumer_on_the_next_poll(
    bus: RedisStreamsEventBus,
) -> None:
    """`read_group` only ever asks for `">"` (new messages) — this proves
    that is actually true against real Redis, not just documented as intent."""
    stream = _stream()
    await bus.ensure_group(stream, "workers")
    await bus.publish(stream, {"job_id": "one-shot"})

    first = await bus.read_group(stream, "workers", "consumer-1", block_ms=100)
    assert len(first) == 1

    second = await bus.read_group(stream, "workers", "consumer-1", block_ms=100)
    assert second == []


async def test_ack_removes_the_message_from_the_pending_entries_list(
    bus: RedisStreamsEventBus, redis_url: str
) -> None:
    stream = _stream()
    await bus.ensure_group(stream, "workers")
    await bus.publish(stream, {"job_id": "acked"})
    delivered = await bus.read_group(stream, "workers", "consumer-1", block_ms=100)
    message_id = delivered[0].id

    await bus.ack(stream, "workers", message_id)

    raw_client: Redis = Redis.from_url(redis_url, decode_responses=True)
    pending = await raw_client.xpending(stream, "workers")
    assert pending["pending"] == 0
    await raw_client.aclose()


async def test_a_second_consumer_in_the_group_does_not_see_the_first_consumers_message(
    bus: RedisStreamsEventBus,
) -> None:
    """Competing consumers, not broadcast — each entry goes to exactly one
    consumer in the group, the property that makes this safe for two worker
    replicas polling the same stream."""
    stream = _stream()
    await bus.ensure_group(stream, "workers")
    await bus.publish(stream, {"job_id": "only-one-owner"})

    to_first = await bus.read_group(stream, "workers", "consumer-1", block_ms=100)
    to_second = await bus.read_group(stream, "workers", "consumer-2", block_ms=100)

    assert len(to_first) == 1
    assert to_second == []


async def test_publish_rejects_when_redis_is_unreachable() -> None:
    unreachable = Redis.from_url(
        "redis://127.0.0.1:1/0", decode_responses=True, socket_connect_timeout=1
    )
    bus = RedisStreamsEventBus(unreachable)

    with pytest.raises(DependencyUnavailableError):
        await bus.publish(_stream(), {"job_id": "x"})
    await unreachable.aclose()
