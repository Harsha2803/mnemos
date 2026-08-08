"""Knowledge routes: upload a document, list/inspect/delete it.

Authenticated by doing nothing, same as every route since `A0`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import BaseModel

from mnemos.core.config import Settings
from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.features.knowledge.application.service import KnowledgeService
from mnemos.features.knowledge.domain import DocumentId, DocumentSummary

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class DocumentResponse(BaseModel):
    id: str
    title: str
    media_type: str
    byte_size: int
    status: str
    superseded_by: str | None
    chunk_count: int
    created_at: str


def _document_response(summary: DocumentSummary) -> DocumentResponse:
    return DocumentResponse(
        id=str(summary.id),
        title=summary.title,
        media_type=summary.media_type,
        byte_size=summary.byte_size,
        status=summary.status,
        superseded_by=str(summary.superseded_by) if summary.superseded_by else None,
        chunk_count=summary.chunk_count,
        created_at=summary.created_at.isoformat(),
    )


def _service(request: Request) -> KnowledgeService:
    service = getattr(request.app.state, "knowledge_service", None)
    if not isinstance(service, KnowledgeService):  # pragma: no cover - the lifespan sets it
        msg = "knowledge service is not configured"
        raise RuntimeError(msg)
    return service


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):  # pragma: no cover - the lifespan sets it
        msg = "settings are not configured"
        raise RuntimeError(msg)
    return settings


def _parse_document_id(raw: str) -> DocumentId:
    try:
        return DocumentId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError(f"document {raw} not found") from exc


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[KnowledgeService, Depends(_service)],
    settings: Annotated[Settings, Depends(_settings)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
) -> DocumentResponse:
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise ValidationError(
            f"file exceeds the {settings.max_upload_bytes} byte upload limit", field="file"
        )
    media_type = file.content_type or "application/octet-stream"
    document = await service.upload_document(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        title=title or file.filename or "Untitled document",
        media_type=media_type,
        data=data,
    )
    return _document_response(document)


@router.get("/documents")
async def list_documents(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[KnowledgeService, Depends(_service)],
) -> list[DocumentResponse]:
    documents = await service.list_documents(org_id=caller.principal.org_id)
    return [_document_response(d) for d in documents]


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[KnowledgeService, Depends(_service)],
) -> DocumentResponse:
    document = await service.get_document(
        org_id=caller.principal.org_id, document_id=_parse_document_id(document_id)
    )
    return _document_response(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[KnowledgeService, Depends(_service)],
) -> None:
    await service.delete_document(
        org_id=caller.principal.org_id, document_id=_parse_document_id(document_id)
    )
