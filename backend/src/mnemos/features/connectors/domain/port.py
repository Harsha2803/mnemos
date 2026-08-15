"""The `SourceConnector` port: what any content source can do, regardless of
where the content actually lives.

Two methods only — `list_items` and `fetch` — because that is everything a
connector needs to do (browse, then read one item) and everything the worker
(deliverable 4) needs to drive ingestion. Registration, config validation and
encryption are `application/service.py`'s job, not the port's: a `Protocol`
this narrow is what lets three unrelated backends (object storage, a local
filesystem, a curated URL list) satisfy it without sharing a base class.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SourceItem:
    """One browsable unit at a source: a key, a file, a URL. `uri` is
    connector-relative — an S3 key, a path relative to the local-fs root, or
    the URL itself — and is exactly what a later `fetch(uri)` call takes."""

    uri: str
    name: str
    size_bytes: int
    content_type: str
    modified_at: datetime | None


class SourceConnector(Protocol):
    async def list_items(self) -> Sequence[SourceItem]: ...

    async def fetch(self, uri: str) -> bytes: ...
