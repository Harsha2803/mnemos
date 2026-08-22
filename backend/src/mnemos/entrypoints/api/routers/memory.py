"""Authenticated memory lifecycle and bitemporal history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mnemos.core.errors import ValidationError
from mnemos.core.types import MemoryKind
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.features.memory.application import MemoryService
from mnemos.features.memory.domain import MemoryHistory, MemoryId, MemoryRecord, MemoryWriteResult

router = APIRouter(prefix="/memories", tags=["memory"])


class MemoryWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_kind: str = Field(min_length=1, max_length=64)
    subject_ref: str = Field(min_length=1, max_length=500)
    subject_name: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=500)
    object_text: str = Field(min_length=1, max_length=16_000)
    kind: Literal["fact", "preference", "decision", "observation"] = "fact"
    scope: dict[str, str] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def timestamps_are_aware(self) -> Self:
        for field_name in ("valid_from", "valid_to"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must include a timezone")
        return self


class MemorySubjectResponse(BaseModel):
    id: str
    kind: str
    external_ref: str
    display_name: str


class MemoryResponse(BaseModel):
    id: str
    subject: MemorySubjectResponse
    predicate: str
    object_text: str
    kind: str
    status: str
    scope: dict[str, str]
    valid_from: str
    valid_to: str
    recorded_at: str
    retracted_at: str | None
    confidence: float
    trust_tier: int
    source_kind: str
    source_ref: str | None


class MemoryWriteResponse(BaseModel):
    claim: MemoryResponse
    superseded: list[str]


class MemoryEdgeResponse(BaseModel):
    id: str
    source_id: str
    target_id: str
    kind: str
    rationale: str | None
    created_at: str


class MemoryHistoryResponse(BaseModel):
    claims: list[MemoryResponse]
    edges: list[MemoryEdgeResponse]


def _service(request: Request) -> MemoryService:
    service = getattr(request.app.state, "memory_service", None)
    if not isinstance(service, MemoryService):  # pragma: no cover - lifespan owns wiring
        raise RuntimeError("memory service is not configured")
    return service


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: MemoryWriteRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[MemoryService, Depends(_service)],
) -> MemoryWriteResponse:
    result = await _write(service=service, caller=caller, body=body)
    return _write_response(result)


@router.post("/{memory_id}/supersede", status_code=status.HTTP_201_CREATED)
async def supersede_memory(
    memory_id: str,
    body: MemoryWriteRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[MemoryService, Depends(_service)],
) -> MemoryWriteResponse:
    result = await _write(
        service=service,
        caller=caller,
        body=body,
        supersede_id=_memory_id(memory_id),
    )
    return _write_response(result)


@router.post("/{memory_id}/retract", status_code=status.HTTP_204_NO_CONTENT)
async def retract_memory(
    memory_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[MemoryService, Depends(_service)],
) -> None:
    await service.retract(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        memory_id=_memory_id(memory_id),
    )


@router.get("")
async def list_memory_history(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[MemoryService, Depends(_service)],
    subject_ref: Annotated[str | None, Query(max_length=500)] = None,
    as_of: Annotated[datetime | None, Query()] = None,
    believed_at: Annotated[datetime | None, Query()] = None,
    include_retracted: Annotated[bool, Query()] = True,
) -> MemoryHistoryResponse:
    history = await service.history(
        org_id=caller.principal.org_id,
        caller_tags=tuple(caller.principal.tags.slugs),
        subject_ref=subject_ref,
        as_of=as_of,
        believed_at=believed_at,
        include_retracted=include_retracted,
    )
    return _history_response(history)


async def _write(
    *,
    service: MemoryService,
    caller: AuthenticatedCaller,
    body: MemoryWriteRequest,
    supersede_id: MemoryId | None = None,
) -> MemoryWriteResult:
    return await service.create(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        subject_kind=body.subject_kind,
        subject_ref=body.subject_ref,
        subject_name=body.subject_name,
        predicate=body.predicate,
        object_text=body.object_text,
        kind=MemoryKind(body.kind),
        scope=body.scope,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        confidence=body.confidence,
        supersede_id=supersede_id,
    )


def _memory_response(record: MemoryRecord) -> MemoryResponse:
    return MemoryResponse(
        id=str(record.id),
        subject=MemorySubjectResponse(
            id=str(record.subject.id),
            kind=record.subject.kind,
            external_ref=record.subject.external_ref,
            display_name=record.subject.display_name,
        ),
        predicate=record.predicate,
        object_text=record.object_text,
        kind=record.kind.value,
        status=record.status.value,
        scope=record.scope,
        valid_from=record.valid_from.isoformat(),
        valid_to=record.valid_to.isoformat(),
        recorded_at=record.recorded_at.isoformat(),
        retracted_at=record.retracted_at.isoformat() if record.retracted_at else None,
        confidence=record.confidence,
        trust_tier=int(record.trust_tier),
        source_kind=record.source_kind,
        source_ref=record.source_ref,
    )


def _write_response(result: MemoryWriteResult) -> MemoryWriteResponse:
    return MemoryWriteResponse(
        claim=_memory_response(result.claim),
        superseded=[str(item) for item in result.superseded],
    )


def _history_response(history: MemoryHistory) -> MemoryHistoryResponse:
    return MemoryHistoryResponse(
        claims=[_memory_response(record) for record in history.claims],
        edges=[
            MemoryEdgeResponse(
                id=str(edge.id),
                source_id=str(edge.source_id),
                target_id=str(edge.target_id),
                kind=edge.kind.value,
                rationale=edge.rationale,
                created_at=edge.created_at.isoformat(),
            )
            for edge in history.edges
        ],
    )


def _memory_id(value: str) -> MemoryId:
    try:
        return MemoryId(uuid.UUID(value))
    except ValueError as exc:
        raise ValidationError("memory_id must be a UUID", field="memory_id") from exc
