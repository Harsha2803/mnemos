"""Replay the persisted context artifact attached to an assistant message."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.chat.domain import ChatMessageId
from mnemos.features.context.application import ContextService
from mnemos.features.context.domain import ContextBundleSummary
from mnemos.features.identity.application.principals import AuthenticatedCaller

router = APIRouter(prefix="/context", tags=["context"])


class BundleItemResponse(BaseModel):
    id: str
    position: int
    section: str
    operator: str
    text: str
    tokens: int
    raw_score: float
    rrf_score: float
    utility: float
    density: float
    trust_tier: int
    source_kind: str
    source_ref: str
    document_title: str | None
    acl_rule: str
    memory_id: str | None


class RejectionResponse(BaseModel):
    key: str
    section: str
    source_kind: str
    source_ref: str
    reason: str
    tokens: int
    utility: float
    detail: str | None


class LineageResponse(BaseModel):
    source_id: str
    target_id: str
    kind: str
    rationale: str | None


class ContextBundleResponse(BaseModel):
    id: str
    digest: str
    flow: str
    token_budget: int
    tokens_consumed: int
    compiled_prompt: str
    budget_report: dict[str, object]
    explain: dict[str, object]
    admitted: list[BundleItemResponse]
    rejections: list[RejectionResponse]
    lineage: list[LineageResponse]
    created_at: str


def _service(request: Request) -> ContextService:
    service = getattr(request.app.state, "context_service", None)
    if not isinstance(service, ContextService):  # pragma: no cover - lifespan owns wiring
        raise RuntimeError("context service is not configured")
    return service


@router.get("/messages/{message_id}/bundle")
async def get_message_bundle(
    message_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ContextService, Depends(_service)],
) -> ContextBundleResponse:
    bundle = await service.get_for_message(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        message_id=_message_id(message_id),
    )
    if bundle is None:
        raise NotFoundError(f"context bundle for message {message_id} not found")
    return _response(bundle)


def _response(bundle: ContextBundleSummary) -> ContextBundleResponse:
    return ContextBundleResponse(
        id=str(bundle.id),
        digest=bundle.digest,
        flow=bundle.flow,
        token_budget=bundle.token_budget,
        tokens_consumed=bundle.tokens_consumed,
        compiled_prompt=bundle.compiled_prompt,
        budget_report=dict(bundle.budget_report),
        explain=dict(bundle.explain),
        admitted=[
            BundleItemResponse(
                id=str(item.id),
                position=item.position,
                section=item.section,
                operator=item.operator.value,
                text=item.text,
                tokens=item.tokens,
                raw_score=item.raw_score,
                rrf_score=item.rrf_score,
                utility=item.utility,
                density=item.density,
                trust_tier=int(item.trust_tier),
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                document_title=item.document_title,
                acl_rule=item.acl_rule,
                memory_id=str(item.memory_id) if item.memory_id is not None else None,
            )
            for item in bundle.admitted
        ],
        rejections=[
            RejectionResponse(
                key=item.key,
                section=item.section,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                reason=item.reason,
                tokens=item.tokens,
                utility=item.utility,
                detail=item.detail,
            )
            for item in bundle.rejections
        ],
        lineage=[
            LineageResponse(
                source_id=str(edge.source_id),
                target_id=str(edge.target_id),
                kind=edge.kind,
                rationale=edge.rationale,
            )
            for edge in bundle.lineage
        ],
        created_at=bundle.created_at.isoformat(),
    )


def _message_id(value: str) -> ChatMessageId:
    try:
        return ChatMessageId(uuid.UUID(value))
    except ValueError as exc:
        raise ValidationError("message_id must be a UUID", field="message_id") from exc
