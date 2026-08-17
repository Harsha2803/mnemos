"""`SourceConnector` over the existing `ObjectStore` port — a bucket and a
prefix, browsed and fetched through the same abstraction A2's manual-upload
path already uses, so this is a second caller of that port rather than a
second MinIO client."""

from __future__ import annotations

import mimetypes
from collections.abc import Sequence

from mnemos.core.errors import ValidationError
from mnemos.features.connectors.domain import SourceItem
from mnemos.platform.objectstore.port import ObjectStore


class S3Connector:
    def __init__(self, *, store: ObjectStore, prefix: str) -> None:
        self._store = store
        self._prefix = prefix

    async def list_items(self) -> Sequence[SourceItem]:
        metas = await self._store.list(self._prefix)
        return [
            SourceItem(
                uri=meta.key,
                name=meta.key.rsplit("/", 1)[-1],
                size_bytes=meta.size_bytes,
                content_type=mimetypes.guess_type(meta.key)[0] or "application/octet-stream",
                modified_at=meta.modified_at,
            )
            for meta in metas
        ]

    async def fetch(self, uri: str) -> bytes:
        if not uri.startswith(self._prefix):
            raise ValidationError(
                "uri is outside the connector's configured prefix", uri=uri, prefix=self._prefix
            )
        return await self._store.get(uri)
