"""`ConnectorService.register` — validated and rejected before anything is
persisted, the same "empty allowlist means no schemas, never every schema"
discipline `DatasourceService.register`/`test_register_rejects_an_empty_
allowlist` established for `allowed_schemas`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from mnemos.core.config import Settings
from mnemos.core.ids import uuid7
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.application.factory import ConnectorFactory
from mnemos.features.connectors.application.ports import ContentSourceRecord
from mnemos.features.connectors.application.service import ConnectorService
from mnemos.features.connectors.domain import SourceId
from mnemos.features.identity.domain import OrgId

TEST_KEY = SourceConfigCipher(key="zyE7WKGQXXwuWC7pvMVZ3qbkXUliL3BRmD8Lzk89qu4=")
ORG = OrgId(uuid7())


class FakeRepository:
    def __init__(self) -> None:
        self._rows: dict[tuple[OrgId, str], ContentSourceRecord] = {}

    async def get_by_slug(self, *, org_id: OrgId, slug: str) -> ContentSourceRecord | None:
        return self._rows.get((org_id, slug))

    async def create(
        self, *, org_id: OrgId, slug: str, name: str, kind: str, config_encrypted: bytes
    ) -> ContentSourceRecord:
        record = ContentSourceRecord(
            id=SourceId(uuid7()),
            org_id=org_id,
            slug=slug,
            name=name,
            kind=kind,
            config_encrypted=config_encrypted,
            is_enabled=True,
            created_at=datetime.now(tz=UTC),
        )
        self._rows[(org_id, slug)] = record
        return record

    async def list_all(self, *, org_id: OrgId) -> Sequence[ContentSourceRecord]:
        return [r for (o, _), r in self._rows.items() if o == org_id]


def _service(*, local_fs_allowed_roots: Sequence[str] = ()) -> ConnectorService:
    settings = Settings()
    factory = ConnectorFactory(settings=settings, cipher=TEST_KEY, http_client=httpx.AsyncClient())
    return ConnectorService(
        repository=FakeRepository(),
        cipher=TEST_KEY,
        factory=factory,
        local_fs_allowed_roots=local_fs_allowed_roots,
    )


async def test_register_rejects_an_empty_bucket_for_s3() -> None:
    service = _service()

    with pytest.raises(ValueError, match="bucket"):
        await service.register(org_id=ORG, slug="src", name="Src", kind="s3", config={})


async def test_register_rejects_an_empty_root_for_local_fs() -> None:
    service = _service()

    with pytest.raises(ValueError, match="root"):
        await service.register(org_id=ORG, slug="src", name="Src", kind="local_fs", config={})


async def test_register_rejects_a_root_outside_the_operator_approved_roots(
    tmp_path: Path,
) -> None:
    """Default-deny even when a non-empty `root` is supplied: the per-
    registration root alone is not the allowlist, the deployment-operator
    setting is."""
    approved = tmp_path / "approved"
    approved.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    service = _service(local_fs_allowed_roots=[str(approved)])

    with pytest.raises(ValueError, match="operator-approved"):
        await service.register(
            org_id=ORG, slug="src", name="Src", kind="local_fs", config={"root": str(elsewhere)}
        )


async def test_register_rejects_local_fs_when_no_roots_are_operator_approved(
    tmp_path: Path,
) -> None:
    service = _service(local_fs_allowed_roots=())

    with pytest.raises(ValueError, match="operator-approved"):
        await service.register(
            org_id=ORG, slug="src", name="Src", kind="local_fs", config={"root": str(tmp_path)}
        )


async def test_register_accepts_a_root_inside_an_operator_approved_root(tmp_path: Path) -> None:
    subdir = tmp_path / "docs"
    subdir.mkdir()
    service = _service(local_fs_allowed_roots=[str(tmp_path)])

    record = await service.register(
        org_id=ORG, slug="src", name="Src", kind="local_fs", config={"root": str(subdir)}
    )

    assert record.kind == "local_fs"
    decrypted = json.loads(TEST_KEY.decrypt(record.config_encrypted))
    assert decrypted == {"root": str(subdir)}


async def test_register_rejects_empty_urls_for_http() -> None:
    service = _service()

    with pytest.raises(ValueError, match="urls"):
        await service.register(org_id=ORG, slug="src", name="Src", kind="http", config={"urls": []})


async def test_register_rejects_an_http_url_that_fails_the_ssrf_deny_list() -> None:
    service = _service()

    with pytest.raises(Exception, match="denied address range"):
        await service.register(
            org_id=ORG,
            slug="src",
            name="Src",
            kind="http",
            config={"urls": ["http://127.0.0.1/internal"]},
        )


async def test_register_rejects_an_unknown_kind() -> None:
    service = _service()

    with pytest.raises(ValueError, match="unknown connector kind"):
        await service.register(org_id=ORG, slug="src", name="Src", kind="ftp", config={})


async def test_config_is_encrypted_at_rest_not_stored_as_plaintext_json() -> None:
    service = _service(local_fs_allowed_roots=["/tmp"])

    record = await service.register(
        org_id=ORG, slug="src", name="Src", kind="local_fs", config={"root": "/tmp"}
    )

    assert b"/tmp" not in record.config_encrypted


async def test_list_items_builds_a_connector_from_the_registered_config_and_browses_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_text("hello")
    service = _service(local_fs_allowed_roots=[str(tmp_path)])
    await service.register(
        org_id=ORG, slug="src", name="Src", kind="local_fs", config={"root": str(tmp_path)}
    )

    items = await service.list_items(org_id=ORG, slug="src")

    assert [item.uri for item in items] == ["a.txt"]


async def test_list_items_raises_for_an_unregistered_slug() -> None:
    service = _service()

    with pytest.raises(LookupError):
        await service.list_items(org_id=ORG, slug="does-not-exist")
