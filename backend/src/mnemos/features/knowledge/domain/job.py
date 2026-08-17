"""Pure records for an ingestion job — the shape the worker (`B1` deliverable
4) passes around instead of an ORM row, same reasoning as `document.py`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import NewType
from uuid import UUID

from mnemos.features.identity.domain import OrgId
from mnemos.features.knowledge.domain.ids import DocumentId

JobId = NewType("JobId", UUID)

#: The one `ingest_job.kind` `B1` produces. Shared by `entrypoints/cli.py`'s
#: `connector ingest` (the producer) and `entrypoints/worker/main.py` (the
#: consumer) so the two cannot silently drift onto different literal strings.
CONNECTOR_INGEST_KIND = "connector_ingest"


@dataclass(frozen=True, slots=True)
class ClaimedIngestJob:
    """One `ingest_job` row, already transitioned to `running` by the claim
    that produced this record — there is no unclaimed variant, because
    nothing outside `IngestJobRepository.claim_next` ever needs one."""

    id: JobId
    org_id: OrgId
    kind: str
    payload: Mapping[str, str]
    document_id: DocumentId | None
    attempts: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class IngestJobEventRecord:
    id: UUID
    job_id: JobId
    from_status: str | None
    to_status: str
    owner_id: str | None
    detail: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class IngestJobRecord:
    id: JobId
    org_id: OrgId
    kind: str
    status: str
    payload: Mapping[str, str]
    document_id: DocumentId | None
    attempts: int
    max_attempts: int
    total_units: int
    done_units: int
    owner_id: str | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime
    events: tuple[IngestJobEventRecord, ...]
