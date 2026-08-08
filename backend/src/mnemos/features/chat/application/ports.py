"""What `ChatService` needs from persistence, named as a `Protocol` so the
service can be tested against an in-memory fake and the adapter stays
swappable (CodingStandards §5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from mnemos.features.chat.domain import (
    ChatMessageId,
    ChatMessageRecord,
    ChatSessionId,
    ChatSessionSummary,
)
from mnemos.features.identity.domain import OrgId, UserId


class ChatRepository(Protocol):
    async def create_session(
        self, *, org_id: OrgId, user_id: UserId, title: str
    ) -> ChatSessionSummary: ...

    async def list_sessions(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        limit: int,
        before: tuple[datetime, ChatSessionId] | None,
    ) -> Sequence[ChatSessionSummary]:
        """Newest first by `(sort_key, id)`. `before`, when given, is the cursor
        of the last row the caller already has — the pagination boundary lives
        in the repository because only it knows the sort key's SQL shape."""
        ...

    async def get_session(
        self, *, org_id: OrgId, session_id: ChatSessionId
    ) -> ChatSessionSummary | None: ...

    async def rename_session(
        self, *, org_id: OrgId, session_id: ChatSessionId, title: str
    ) -> ChatSessionSummary | None: ...

    async def delete_session(self, *, org_id: OrgId, session_id: ChatSessionId) -> bool: ...

    async def list_messages(
        self, *, org_id: OrgId, session_id: ChatSessionId
    ) -> Sequence[ChatMessageRecord]: ...

    async def append_user_message(
        self, *, org_id: OrgId, session_id: ChatSessionId, content: str
    ) -> ChatMessageRecord:
        """Also stamps `chat_session.last_message_at`, in the same transaction —
        a session whose newest message does not move it to the top of the list
        is a chat history that looks stale the moment it stops being empty."""
        ...

    async def append_assistant_message(
        self,
        *,
        org_id: OrgId,
        session_id: ChatSessionId,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        model: str,
        finish_reason: str,
    ) -> ChatMessageRecord: ...


__all__ = ["ChatMessageId", "ChatRepository"]
