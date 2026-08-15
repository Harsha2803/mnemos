"""The `EventBus` port: a durable, replayable log of ingestion events.

Redis Streams (`XADD` / consumer-group `XREADGROUP`), not `platform/cache.py`'s
pub/sub. Pub/sub only reaches whoever is subscribed at the instant of publish
and keeps nothing once delivered — fine for the realtime gateway's existing
"forward whatever arrives" job, wrong for the thing `B1` actually needs: a
worker that dies between claiming an `ingest_job` and finishing it must not
lose the events it already emitted. A stream keeps every `publish`ed entry on
disk until a consumer group `ack`s it, so `read_group` after a restart resumes
from the group's last acknowledged position rather than from "now".

Two methods to write, two to read — `SourceConnector` (deliverable 1) is the
same shape of narrow `Protocol` for the same reason: the abstraction is the
deliverable, and every method here is something a real caller (deliverable 4's
worker, or a future consumer-group reader) actually needs, not a speculative
extra.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StreamMessage:
    """One delivered entry: its Streams-assigned id and its fields."""

    id: str
    fields: Mapping[str, str]


class EventBus(Protocol):
    async def publish(self, stream: str, fields: Mapping[str, str]) -> str: ...

    async def ensure_group(self, stream: str, group: str) -> None: ...

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 5000,
    ) -> Sequence[StreamMessage]: ...

    async def ack(self, stream: str, group: str, message_id: str) -> None: ...
