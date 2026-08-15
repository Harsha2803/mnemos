"""`SourceConnector` over a local filesystem directory, scoped to an
operator-approved root.

**Default-deny outside the root** — the same discipline `A3`'s
`allowed_schemas` enforces. Two things make that real rather than aspirational:

1. `fetch` refuses an absolute `uri` outright, before ever joining it onto the
   root. `Path("/a") / "/etc/passwd"` is `Path("/etc/passwd")` — pathlib's `/`
   operator *replaces* the left side when the right side is absolute, so a
   join-then-check-containment approach would let an absolute `uri` escape the
   root before containment is ever checked.
2. Every resolved path is checked with `is_relative_to(root)` *after*
   `Path.resolve()`, which also follows symlinks — a symlink inside the root
   pointing outside it resolves to its real, external target before the
   containment check runs, so it cannot be used to escape either.

Blocking filesystem calls run through `anyio.to_thread.run_sync`
(CodingStandards §3), the same discipline `S3ObjectStore` uses for `boto3`.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import anyio

from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.features.connectors.domain import SourceItem


class LocalFsConnector:
    def __init__(self, *, root: str) -> None:
        self._root = Path(root).resolve()

    async def list_items(self) -> Sequence[SourceItem]:
        return await anyio.to_thread.run_sync(self._list_items_sync)

    def _list_items_sync(self) -> list[SourceItem]:
        items: list[SourceItem] = []
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            rel = path.relative_to(self._root).as_posix()
            items.append(
                SourceItem(
                    uri=rel,
                    name=path.name,
                    size_bytes=stat.st_size,
                    content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )
            )
        return items

    async def fetch(self, uri: str) -> bytes:
        return await anyio.to_thread.run_sync(self._fetch_sync, uri)

    def _fetch_sync(self, uri: str) -> bytes:
        if not uri or PurePosixPath(uri).is_absolute() or uri.startswith(("/", "\\")):
            raise ValidationError("uri must be a path relative to the connector's root", uri=uri)

        candidate = (self._root / uri).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValidationError("uri escapes the connector's configured root", uri=uri)
        if not candidate.is_file():
            raise NotFoundError(f"no file at {uri!r}")
        return candidate.read_bytes()
