"""The object storage port.

A narrow `Protocol` — `put`, `get`, `delete` — rather than anything shaped like
boto3's client, so the deployment target (MinIO locally, S3 in a real
deployment) is a config choice and not a call-site change (ADAPTATION §3). The
full `SourceConnector` abstraction over multiple backends is `B1`; this is the
one adapter A2 needs to store an uploaded file and read it back for a citation.
"""

from __future__ import annotations

from typing import Protocol


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
