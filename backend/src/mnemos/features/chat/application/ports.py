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
    CitationInput,
    CitationRecord,
    FolderId,
    FolderRecord,
)
from mnemos.features.identity.domain import OrgId, UserId


class _UnsetType:
    """Distinguishes "the caller did not mention `folder_id`" (leave it alone)
    from "the caller sent `folder_id: null`" (move to no folder) — a plain
    `None` default cannot carry that distinction because `None` is also the
    valid value meaning "no folder" (TRACKER §5 deliverable 1)."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _UnsetType()


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
        self,
        *,
        org_id: OrgId,
        session_id: ChatSessionId,
        title: str | None = None,
        folder_id: FolderId | _UnsetType | None = UNSET,
    ) -> ChatSessionSummary | None:
        """`title=None` leaves the title untouched (every stored title is a
        non-null string, so `None` cannot be a real value to set). `folder_id`
        needs the three-state `UNSET` sentinel instead, because `None` *is* a
        real value there — "no folder" — distinct from "don't touch this
        field" (see `_UnsetType`)."""
        ...

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
        flow: str | None = None,
        router_rationale: str | None = None,
    ) -> ChatMessageRecord: ...

    async def add_citations(
        self, *, org_id: OrgId, message_id: ChatMessageId, citations: Sequence[CitationInput]
    ) -> None:
        """`flows/rag` calls this after `append_assistant_message` returns —
        a citation without a message to attach to cannot exist, so the two
        are always sequential rather than one call carrying both."""
        ...

    async def list_citations(
        self, *, org_id: OrgId, session_id: ChatSessionId
    ) -> Sequence[CitationRecord]: ...

    async def create_folder(self, *, org_id: OrgId, user_id: UserId, name: str) -> FolderRecord: ...

    async def list_folders(self, *, org_id: OrgId, user_id: UserId) -> Sequence[FolderRecord]:
        """Ordered `position ASC, id ASC` — the explicit `id` tiebreak matches
        the fix TRACKER's 2026-08-22 notes made to `SqlToolRepository` after a
        non-unique sort caused an intermittent, hard-to-reproduce bug; every
        new list query in this milestone repeats that fix rather than the
        still-unfixed shape in `features/knowledge`'s `list_documents`."""
        ...

    async def get_folder(
        self, *, org_id: OrgId, user_id: UserId, folder_id: FolderId
    ) -> FolderRecord | None: ...

    async def rename_folder(
        self, *, org_id: OrgId, folder_id: FolderId, name: str | None, position: int | None
    ) -> FolderRecord | None: ...

    async def delete_folder(self, *, org_id: OrgId, folder_id: FolderId) -> bool:
        """The FK (`chat_session.folder_id`) is `ondelete=SET NULL`, so
        deleting the row already un-files its sessions at the database level —
        no service-side cleanup query is needed here."""
        ...


__all__ = ["UNSET", "ChatMessageId", "ChatRepository", "_UnsetType"]
