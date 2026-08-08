"""Pure records for a document — the shape the application and API layers
pass around instead of an ORM row (CodingStandards §6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mnemos.features.identity.domain import OrgId
from mnemos.features.knowledge.domain.ids import DocumentId


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    id: DocumentId
    org_id: OrgId
    title: str
    media_type: str
    byte_size: int
    status: str
    superseded_by: DocumentId | None
    chunk_count: int
    created_at: datetime
