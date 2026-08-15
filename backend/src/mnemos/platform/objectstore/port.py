"""The object storage port.

A narrow `Protocol` — `put`, `get`, `delete`, `list` — rather than anything
shaped like boto3's client, so the deployment target (MinIO locally, S3 in a
real deployment) is a config choice and not a call-site change (ADAPTATION
§3). `put`/`get`/`delete` are what A2 needs to store an uploaded file and
read it back for a citation; `list` is `B1`'s addition — the S3 connector
(`features/connectors/adapters/s3.py`) sits on top of this same port to
browse a bucket+prefix rather than opening a second, parallel MinIO client.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ObjectMeta:
    key: str
    size_bytes: int
    modified_at: datetime | None


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def list(self, prefix: str = "") -> Sequence[ObjectMeta]: ...
