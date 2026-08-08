"""Pure records for a chat session and its messages.

Flat value objects, not ORM rows (CodingStandards §6): an ORM row escaping the
adapter layer carries a lazy-loading session with it, and a lazy load fired
from the streaming path surfaces as a `MissingGreenlet` far from its cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int | None
    model: str | None
    finish_reason: str | None
    error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatSessionDetail:
    """A session plus the messages in it, ordinal-ordered — the shape
    `GET /v1/chat/sessions/{id}` answers with."""

    session: ChatSessionSummary
    messages: tuple[ChatMessageRecord, ...]


@dataclass(frozen=True, slots=True)
class ChatSessionPage:
    sessions: tuple[ChatSessionSummary, ...]
    next_cursor: str | None
