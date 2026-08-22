"""Bookmark routes: save a message with an optional note, remove it, list
them across every session.

Authenticated by doing nothing, same as `chat.py`/`folders.py`. Permission
`chat:write` covers the mutations and `chat:read` covers listing, already
granted to `analyst` and `user` — a bookmark is the caller's own note on the
caller's own message, the same authority level as renaming a session.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from mnemos.core.errors import NotFoundError
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.chat.application.bookmarks import DEFAULT_PAGE_SIZE, BookmarkService
from mnemos.features.chat.domain import BookmarkedMessage, BookmarkRecord, ChatMessageId
from mnemos.features.identity.application.principals import AuthenticatedCaller

router = APIRouter(tags=["chat"])

MAX_LIMIT = 100


class BookmarkResponse(BaseModel):
    id: str
    message_id: str
    note: str | None
    created_at: str


class BookmarkedMessageResponse(BaseModel):
    id: str
    message_id: str
    session_id: str
    session_title: str
    message_role: str
    message_content: str
    note: str | None
    created_at: str


def _bookmark_only_response(record: BookmarkRecord) -> BookmarkResponse:
    return BookmarkResponse(
        id=str(record.id),
        message_id=str(record.message_id),
        note=record.note,
        created_at=record.created_at.isoformat(),
    )


class BookmarkListResponse(BaseModel):
    bookmarks: list[BookmarkedMessageResponse]
    next_cursor: str | None


class UpsertBookmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


def _bookmark_response(item: BookmarkedMessage) -> BookmarkedMessageResponse:
    return BookmarkedMessageResponse(
        id=str(item.bookmark.id),
        message_id=str(item.bookmark.message_id),
        session_id=str(item.session_id),
        session_title=item.session_title,
        message_role=item.message_role.value,
        message_content=item.message_content,
        note=item.bookmark.note,
        created_at=item.bookmark.created_at.isoformat(),
    )


def _service(request: Request) -> BookmarkService:
    service = getattr(request.app.state, "bookmark_service", None)
    if not isinstance(service, BookmarkService):  # pragma: no cover - the lifespan sets it
        msg = "bookmark service is not configured"
        raise RuntimeError(msg)
    return service


def _parse_message_id(raw: str) -> ChatMessageId:
    try:
        return ChatMessageId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError(f"message {raw} not found") from exc


@router.put("/chat/messages/{message_id}/bookmark")
async def upsert_bookmark(
    message_id: str,
    body: UpsertBookmarkRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[BookmarkService, Depends(_service)],
) -> BookmarkResponse:
    record = await service.upsert_bookmark(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        message_id=_parse_message_id(message_id),
        note=body.note,
    )
    return _bookmark_only_response(record)


@router.delete("/chat/messages/{message_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def remove_bookmark(
    message_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[BookmarkService, Depends(_service)],
) -> None:
    await service.remove_bookmark(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        message_id=_parse_message_id(message_id),
    )


@router.get("/chat/bookmarks")
async def list_bookmarks(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[BookmarkService, Depends(_service)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> BookmarkListResponse:
    page = await service.list_bookmarks(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        limit=limit,
        cursor=cursor,
    )
    return BookmarkListResponse(
        bookmarks=[_bookmark_response(item) for item in page.items],
        next_cursor=page.next_cursor,
    )
