"""Identifier generation.

UUIDv7 rather than v4: the first 48 bits are a millisecond timestamp, so primary
keys are time-ordered. That keeps B-tree inserts appending at the right edge
instead of scattering across the index, which matters for the append-heavy tables
(`chat_message`, `inference_call`, `audit_log`). Python's stdlib has no uuid7 yet,
so it is built here from `os.urandom` per RFC 9562.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Protocol


class IdGenerator(Protocol):
    def new(self) -> uuid.UUID: ...


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit unix_ts_ms | version | 12 bits rand | variant | 62 bits rand."""
    ts_ms = time.time_ns() // 1_000_000
    rand = os.urandom(10)

    value = ts_ms << 80
    value |= 0x7 << 76  # version 7
    value |= (rand[0] & 0x0F) << 72  # rand_a (12 bits)
    value |= rand[1] << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= int.from_bytes(rand[2:10], "big") & ((1 << 62) - 1)
    return uuid.UUID(int=value)


class Uuid7Generator:
    def new(self) -> uuid.UUID:
        return uuid7()


class SequentialIdGenerator:
    """Deterministic ids so that benchmark bundle digests are stable run to run."""

    def __init__(self, namespace: str = "mnemos") -> None:
        self._namespace = uuid.uuid5(uuid.NAMESPACE_DNS, namespace)
        self._n = 0

    def new(self) -> uuid.UUID:
        self._n += 1
        return uuid.uuid5(self._namespace, str(self._n))


DEFAULT_ID_GENERATOR = Uuid7Generator()
