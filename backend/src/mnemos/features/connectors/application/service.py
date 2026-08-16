"""`ConnectorService`: register a content source and browse what it contains.

Registration validates and rejects before anything is written — the same
"fail before persisting nonsense" discipline `DatasourceService.register`
follows for `allowed_schemas`. `list_items` is the one place `ConnectorFactory`
gets used outside the worker, so registering and browsing share exactly the
validation and decryption path deliverable 4's ingestion will also go through.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import anyio

from mnemos.core.logging import get_logger
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.adapters.ssrf_guard import resolve_and_pin
from mnemos.features.connectors.application.factory import ConnectorFactory
from mnemos.features.connectors.application.ports import (
    ContentSourceRecord,
    ContentSourceRepository,
)
from mnemos.features.connectors.domain import SourceItem
from mnemos.features.identity.domain import OrgId

log = get_logger(__name__)


class ConnectorService:
    def __init__(
        self,
        *,
        repository: ContentSourceRepository,
        cipher: SourceConfigCipher,
        factory: ConnectorFactory,
        local_fs_allowed_roots: Sequence[str],
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._factory = factory
        self._local_fs_allowed_roots = [Path(r).resolve() for r in local_fs_allowed_roots]

    async def register(
        self, *, org_id: OrgId, slug: str, name: str, kind: str, config: dict[str, object]
    ) -> ContentSourceRecord:
        await self._validate_config(kind=kind, config=config)
        record = await self._repository.create(
            org_id=org_id,
            slug=slug,
            name=name,
            kind=kind,
            config_encrypted=self._cipher.encrypt(json.dumps(config)),
        )
        log.info("connectors.registered", org_id=str(org_id), slug=slug, kind=kind)
        return record

    async def _validate_config(self, *, kind: str, config: dict[str, object]) -> None:
        if kind in ("s3", "minio"):
            bucket = config.get("bucket")
            if not bucket or not isinstance(bucket, str):
                raise ValueError("s3 connector config must set a non-empty 'bucket'")
            return

        if kind == "local_fs":
            root = config.get("root")
            if not root or not isinstance(root, str):
                # Default-deny outside a configured root — the same discipline
                # `DatasourceService.register` enforces for `allowed_schemas`
                # (an empty allowlist means "no schemas", never "every schema").
                raise ValueError("local_fs connector config must set a non-empty 'root'")
            resolved = await anyio.to_thread.run_sync(lambda: Path(root).resolve())
            if not self._local_fs_allowed_roots or not any(
                resolved == allowed or resolved.is_relative_to(allowed)
                for allowed in self._local_fs_allowed_roots
            ):
                raise ValueError(
                    f"root {root!r} is not inside an operator-approved root "
                    "(MNEMOS_LOCAL_FS_ALLOWED_ROOTS)"
                )
            return

        if kind == "http":
            urls = config.get("urls")
            if not urls or not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
                raise ValueError("http connector config must set a non-empty list of 'urls'")
            # Fail at registration, not at first ingest: an operator-curated
            # URL that already resolves to a denied range should never make it
            # into a saved connector (ThreatModel.md §3⑥).
            for url in urls:
                await resolve_and_pin(url)
            return

        raise ValueError(f"unknown connector kind {kind!r}")

    async def list_sources(self, *, org_id: OrgId) -> Sequence[ContentSourceRecord]:
        return await self._repository.list_all(org_id=org_id)

    async def require_source(self, *, org_id: OrgId, slug: str) -> ContentSourceRecord:
        record = await self._repository.get_by_slug(org_id=org_id, slug=slug)
        if record is None:
            raise LookupError(f"no content source registered for org {org_id} with slug {slug!r}")
        return record

    async def list_items(self, *, org_id: OrgId, slug: str) -> Sequence[SourceItem]:
        record = await self.require_source(org_id=org_id, slug=slug)
        connector = self._factory.build(record)
        return await connector.list_items()

    async def fetch_item(self, *, org_id: OrgId, slug: str, uri: str) -> tuple[str, bytes]:
        """Returns `(source_kind, content)` — the source's own kind travels
        with the fetched bytes because `Document.source_kind` (`B1`
        deliverable 4's worker) records where content actually came from,
        not just that it arrived."""
        record = await self.require_source(org_id=org_id, slug=slug)
        connector = self._factory.build(record)
        data = await connector.fetch(uri)
        return record.kind, data
