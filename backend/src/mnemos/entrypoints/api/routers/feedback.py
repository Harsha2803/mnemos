"""Feedback routes: rate a message up or down, with an optional comment.

Authenticated by doing nothing, same as `chat.py`/`bookmarks.py`. Permission
`chat:write` covers the mutation, already granted to `analyst` and `user` —
rating an answer is the caller's own reaction to the caller's own message.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from mnemos.core.errors import NotFoundError
from mnemos.core.types import FeedbackRating
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.chat.application.feedback import FeedbackService
from mnemos.features.chat.domain import ChatMessageId, FeedbackRecord
from mnemos.features.identity.application.principals import AuthenticatedCaller

router = APIRouter(tags=["chat"])


class FeedbackResponse(BaseModel):
    id: str
    message_id: str
    rating: Literal["up", "down"]
    comment: str | None
    created_at: str


class UpsertFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


def _feedback_response(record: FeedbackRecord) -> FeedbackResponse:
    return FeedbackResponse(
        id=str(record.id),
        message_id=str(record.message_id),
        rating=record.rating.value,
        comment=record.comment,
        created_at=record.created_at.isoformat(),
    )


def _service(request: Request) -> FeedbackService:
    service = getattr(request.app.state, "feedback_service", None)
    if not isinstance(service, FeedbackService):  # pragma: no cover - the lifespan sets it
        msg = "feedback service is not configured"
        raise RuntimeError(msg)
    return service


def _parse_message_id(raw: str) -> ChatMessageId:
    try:
        return ChatMessageId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError(f"message {raw} not found") from exc


@router.put("/chat/messages/{message_id}/feedback")
async def upsert_feedback(
    message_id: str,
    body: UpsertFeedbackRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[FeedbackService, Depends(_service)],
) -> FeedbackResponse:
    record = await service.upsert_feedback(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        message_id=_parse_message_id(message_id),
        rating=FeedbackRating(body.rating),
        comment=body.comment,
    )
    return _feedback_response(record)


@router.delete("/chat/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def remove_feedback(
    message_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[FeedbackService, Depends(_service)],
) -> None:
    await service.remove_feedback(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        message_id=_parse_message_id(message_id),
    )
