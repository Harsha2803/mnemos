"""Pure records for a chat session and its messages.

Flat value objects, not ORM rows (CodingStandards §6): an ORM row escaping the
adapter layer carries a lazy-loading session with it, and a lazy load fired
from the streaming path surfaces as a `MissingGreenlet` far from its cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from mnemos.core.types import MessageRole
from mnemos.features.chat.domain.ids import ChatMessageId, ChatSessionId
from mnemos.features.identity.domain import OrgId, UserId


@dataclass(frozen=True, slots=True)
class ChatSessionSummary:
    id: ChatSessionId
    org_id: OrgId
    user_id: UserId
    title: str
    is_archived: bool
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ChatMessageRecord:
    id: ChatMessageId
    session_id: ChatSessionId
    ordinal: int
    role: MessageRole
    content: str
    flow: str | None
    router_rationale: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int | None
    model: str | None
    finish_reason: str | None
    error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CitationInput:
    """What `flows/rag` hands `ChatRepository.add_citations` — no id yet,
    unlike `CitationRecord`, which is the read-back shape."""

    marker: int
    document_id: UUID
    chunk_id: UUID
    quoted_text: str
    start_char: int
    end_char: int
    page_number: int | None
    score: float


@dataclass(frozen=True, slots=True)
class CitationRecord:
    id: UUID
    message_id: ChatMessageId
    marker: int
    document_id: UUID | None
    chunk_id: UUID | None
    quoted_text: str
    start_char: int | None
    end_char: int | None
    page_number: int | None
    score: float | None


@dataclass(frozen=True, slots=True)
class ChatSessionDetail:
    """A session plus the messages in it, ordinal-ordered — the shape
    `GET /v1/chat/sessions/{id}` answers with."""

    session: ChatSessionSummary
    messages: tuple[ChatMessageRecord, ...]
    citations: tuple[CitationRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatSessionPage:
    sessions: tuple[ChatSessionSummary, ...]
    next_cursor: str | None
