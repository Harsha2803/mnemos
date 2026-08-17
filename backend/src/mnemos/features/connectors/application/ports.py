"""What `ConnectorService` needs from persistence, as a `Protocol` — the
repository satisfies this structurally, matching `features/datasources`'s
pattern."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mnemos.features.connectors.domain import SourceId
from mnemos.features.identity.domain import OrgId


@dataclass(frozen=True, slots=True)
class ContentSourceRecord:
    id: SourceId
    org_id: OrgId
    slug: str
    name: str
    kind: str
    config_encrypted: bytes
    is_enabled: bool
    created_at: datetime


class ContentSourceRepository(Protocol):
    async def get_by_slug(self, *, org_id: OrgId, slug: str) -> ContentSourceRecord | None: ...

    async def create(
        self,
        *,
        org_id: OrgId,
        slug: str,
        name: str,
        kind: str,
        config_encrypted: bytes,
    ) -> ContentSourceRecord: ...

    async def list_all(self, *, org_id: OrgId) -> Sequence[ContentSourceRecord]: ...
