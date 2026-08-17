"""Connector routes: register a content source, browse it, enqueue an ingest.

`B1` deliverable 5's backend slice — the same three calls
`mnemosctl connector register`/`list-items`/`ingest` already make against
`ConnectorService`/`IngestJobRepository`, reachable from a browser instead of
a terminal. The worker (deliverable 4) is still the only thing that ever
transitions a job past `queued`; this router only ever writes that first row.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from mnemos.core.errors import ConflictError, NotFoundError, ValidationError
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.connectors.application.ports import ContentSourceRecord
from mnemos.features.connectors.application.service import ConnectorService
from mnemos.features.connectors.domain import SourceItem
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.features.knowledge.adapters.jobs_repository import IngestJobRepository
from mnemos.features.knowledge.domain import CONNECTOR_INGEST_KIND

router = APIRouter(prefix="/connectors", tags=["connectors"])

ConnectorKind = Literal["s3", "minio", "local_fs", "http"]


class RegisterSourceRequest(BaseModel):
    slug: str
    name: str
    kind: ConnectorKind
    # Exactly one of these three is read, chosen by `kind` — mirroring
    # `entrypoints/cli.py`'s `_connector_config`, which is the only other
    # place a `ConnectorService.register` config dict gets built.
    bucket: str | None = None
    prefix: str | None = None
    root: str | None = None
    urls: list[str] | None = None


class SourceResponse(BaseModel):
    id: str
    slug: str
    name: str
    kind: str
    is_enabled: bool
    created_at: str


class ItemResponse(BaseModel):
    uri: str
    name: str
    size_bytes: int
    content_type: str
    modified_at: str | None


class IngestRequest(BaseModel):
    uri: str


class IngestResponse(BaseModel):
    job_id: str
    status: str
    uri: str


def _source_response(record: ContentSourceRecord) -> SourceResponse:
    return SourceResponse(
        id=str(record.id),
        slug=record.slug,
        name=record.name,
        kind=record.kind,
        is_enabled=record.is_enabled,
        created_at=record.created_at.isoformat(),
    )


def _item_response(item: SourceItem) -> ItemResponse:
    return ItemResponse(
        uri=item.uri,
        name=item.name,
        size_bytes=item.size_bytes,
        content_type=item.content_type,
        modified_at=item.modified_at.isoformat() if item.modified_at else None,
    )


def _config(body: RegisterSourceRequest) -> dict[str, object]:
    if body.kind in ("s3", "minio"):
        if not body.bucket:
            raise ValidationError("bucket is required for an s3 connector", field="bucket")
        return {"bucket": body.bucket, "prefix": body.prefix or ""}
    if body.kind == "local_fs":
        if not body.root:
            raise ValidationError("root is required for a local_fs connector", field="root")
        return {"root": body.root}
    if body.kind == "http":
        if not body.urls:
            raise ValidationError("urls is required for an http connector", field="urls")
        return {"urls": body.urls}
    raise ValidationError(f"unknown connector kind {body.kind!r}", field="kind")  # pragma: no cover


def _service(request: Request) -> ConnectorService:
    service = getattr(request.app.state, "connector_service", None)
    if not isinstance(service, ConnectorService):  # pragma: no cover - the lifespan sets it
        msg = "connector service is not configured"
        raise RuntimeError(msg)
    return service


def _jobs(request: Request) -> IngestJobRepository:
    jobs = getattr(request.app.state, "ingest_jobs", None)
    if not isinstance(jobs, IngestJobRepository):  # pragma: no cover - the lifespan sets it
        msg = "ingest job repository is not configured"
        raise RuntimeError(msg)
    return jobs


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_source(
    body: RegisterSourceRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ConnectorService, Depends(_service)],
) -> SourceResponse:
    config = _config(body)
    try:
        record = await service.register(
            org_id=caller.principal.org_id,
            slug=body.slug,
            name=body.name,
            kind=body.kind,
            config=config,
        )
    except ValueError as exc:
        # `ConnectorService._validate_config` raises plain `ValueError` for a
        # rejected config (missing field, an `http` url outside the SSRF
        # deny-list, a `local_fs` root outside `MNEMOS_LOCAL_FS_ALLOWED_ROOTS`)
        # — translated here, the one boundary a service-layer exception has to
        # cross to become a 422 rather than an unhandled 500.
        raise ValidationError(str(exc)) from exc
    except IntegrityError as exc:
        raise ConflictError(f"a source is already registered with slug {body.slug!r}") from exc
    return _source_response(record)


@router.get("")
async def list_sources(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ConnectorService, Depends(_service)],
) -> list[SourceResponse]:
    sources = await service.list_sources(org_id=caller.principal.org_id)
    return [_source_response(s) for s in sources]


@router.get("/{slug}/items")
async def list_items(
    slug: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ConnectorService, Depends(_service)],
) -> list[ItemResponse]:
    try:
        items = await service.list_items(org_id=caller.principal.org_id, slug=slug)
    except LookupError as exc:
        raise NotFoundError(f"no content source registered with slug {slug!r}") from exc
    return [_item_response(i) for i in items]


@router.post("/{slug}/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_item(
    slug: str,
    body: IngestRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ConnectorService, Depends(_service)],
    jobs: Annotated[IngestJobRepository, Depends(_jobs)],
) -> IngestResponse:
    """Enqueue a `queued` `ingest_job` for one item the source currently
    lists — the second producer `entrypoints/worker/main.py`'s docstring
    already anticipated. Refuses a `uri` the source does not currently list,
    same discipline `mnemosctl connector ingest` enforces, so this can never
    become an arbitrary-fetch primitive for a slug the caller's org owns."""
    try:
        items = await service.list_items(org_id=caller.principal.org_id, slug=slug)
    except LookupError as exc:
        raise NotFoundError(f"no content source registered with slug {slug!r}") from exc

    match = next((i for i in items if i.uri == body.uri), None)
    if match is None:
        raise NotFoundError(f"{body.uri!r} is not a currently listed item of {slug!r}")

    job_id = await jobs.enqueue(
        org_id=caller.principal.org_id,
        kind=CONNECTOR_INGEST_KIND,
        payload={
            "source_slug": slug,
            "item_uri": match.uri,
            "item_name": match.name,
            "content_type": match.content_type,
        },
        idempotency_key=f"{slug}:{match.uri}",
    )
    return IngestResponse(job_id=str(job_id), status="queued", uri=match.uri)
