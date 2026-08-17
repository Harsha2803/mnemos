"""`S3Connector` — sits on top of the `ObjectStore` port (list/get by
prefix) rather than a second, parallel MinIO client."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from mnemos.core.errors import ValidationError
from mnemos.features.connectors.adapters.s3 import S3Connector
from mnemos.platform.objectstore.port import ObjectMeta


class FakeObjectStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:  # pragma: no cover
        self._objects[key] = data

    async def get(self, key: str) -> bytes:
        return self._objects[key]

    async def delete(self, key: str) -> None:  # pragma: no cover - unused here
        del self._objects[key]

    async def list(self, prefix: str = "") -> Sequence[ObjectMeta]:
        return [
            ObjectMeta(key=key, size_bytes=len(data), modified_at=datetime.now(tz=UTC))
            for key, data in self._objects.items()
            if key.startswith(prefix)
        ]


async def test_list_items_only_returns_objects_under_the_prefix() -> None:
    store = FakeObjectStore(
        {
            "acme/reports/q1.pdf": b"q1",
            "acme/reports/q2.pdf": b"q2",
            "acme/other/note.txt": b"note",
        }
    )
    connector = S3Connector(store=store, prefix="acme/reports/")

    items = await connector.list_items()

    assert {item.uri for item in items} == {"acme/reports/q1.pdf", "acme/reports/q2.pdf"}
    assert {item.name for item in items} == {"q1.pdf", "q2.pdf"}


async def test_fetch_returns_the_object_bytes() -> None:
    store = FakeObjectStore({"acme/reports/q1.pdf": b"contents"})
    connector = S3Connector(store=store, prefix="acme/reports/")

    assert await connector.fetch("acme/reports/q1.pdf") == b"contents"


async def test_fetch_refuses_a_key_outside_the_configured_prefix() -> None:
    store = FakeObjectStore({"acme/other/secret.txt": b"nope"})
    connector = S3Connector(store=store, prefix="acme/reports/")

    with pytest.raises(ValidationError):
        await connector.fetch("acme/other/secret.txt")
