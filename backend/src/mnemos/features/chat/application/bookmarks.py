"""Bookmark use cases: save a message with an optional note, remove it, list
them across every session.

A sibling service to `ChatService`/`FolderService`, sharing `ChatRepository` —
the same shape `features/tools/` uses for its two services."""

from __future__ import annotations

import uuid
from datetime import datetime

from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.domain import (
    BookmarkedMessage,
    BookmarkId,
    BookmarkPage,
    BookmarkRecord,
    ChatMessageId,
)
from mnemos.features.identity.domain import OrgId, UserId

DEFAULT_PAGE_SIZE = 20


class BookmarkService:
    def __init__(self, *, repository: ChatRepository) -> None:
        self._repository = repository

    async def upsert_bookmark(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId, note: str | None
    ) -> BookmarkRecord:
        record = await self._repository.upsert_bookmark(
            org_id=org_id, user_id=user_id, message_id=message_id, note=note
        )
        if record is None:
            # "The message does not exist" and "it exists but is not yours"
            # are indistinguishable on the wire — 404 either way, the same
            # convention `_owned_session` established for sessions.
            raise NotFoundError(f"message {message_id} not found")
        return record

    async def remove_bookmark(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId
    ) -> None:
        removed = await self._repository.remove_bookmark(
            org_id=org_id, user_id=user_id, message_id=message_id
        )
        if not removed:
            raise NotFoundError(f"no bookmark on message {message_id}")

    async def list_bookmarks(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> BookmarkPage:
        before = _decode_cursor(cursor) if cursor is not None else None
        rows = await self._repository.list_bookmarks(
            org_id=org_id, user_id=user_id, limit=limit + 1, before=before
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = _encode_cursor(page[-1]) if has_more and page else None
        return BookmarkPage(items=tuple(page), next_cursor=next_cursor)


def _encode_cursor(item: BookmarkedMessage) -> str:
    return f"{item.bookmark.created_at.isoformat()}|{item.bookmark.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, BookmarkId]:
    timestamp, _, raw_id = cursor.rpartition("|")
    if not timestamp or not raw_id:
        raise ValidationError("malformed pagination cursor", field="cursor")
    try:
        return datetime.fromisoformat(timestamp), BookmarkId(uuid.UUID(raw_id))
    except ValueError as exc:
        raise ValidationError("malformed pagination cursor", field="cursor") from exc


__all__ = ["BookmarkService"]
