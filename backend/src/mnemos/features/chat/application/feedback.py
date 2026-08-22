"""Feedback use cases: rate a message up or down, with an optional comment,
and clear a rating.

A sibling service to `ChatService`/`FolderService`/`BookmarkService`, sharing
`ChatRepository` — the same shape `features/tools/` uses for its two
services. No list endpoint here: feedback is per-message state surfaced
through the message itself (`ChatMessageRecord.feedback`), not a standalone
screen — an aggregate feedback view is the `C2`-adjacent extension TRACKER §5
names as out of scope for this milestone."""

from __future__ import annotations

from mnemos.core.errors import NotFoundError
from mnemos.core.types import FeedbackRating
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.domain import ChatMessageId, FeedbackRecord
from mnemos.features.identity.domain import OrgId, UserId


class FeedbackService:
    def __init__(self, *, repository: ChatRepository) -> None:
        self._repository = repository

    async def upsert_feedback(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        message_id: ChatMessageId,
        rating: FeedbackRating,
        comment: str | None,
    ) -> FeedbackRecord:
        record = await self._repository.upsert_feedback(
            org_id=org_id, user_id=user_id, message_id=message_id, rating=rating, comment=comment
        )
        if record is None:
            raise NotFoundError(f"message {message_id} not found")
        return record

    async def remove_feedback(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId
    ) -> None:
        removed = await self._repository.remove_feedback(
            org_id=org_id, user_id=user_id, message_id=message_id
        )
        if not removed:
            raise NotFoundError(f"no feedback on message {message_id}")


__all__ = ["FeedbackService"]
