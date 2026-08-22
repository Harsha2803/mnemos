"""Chat domain: pure types, no SQLAlchemy, no FastAPI, no I/O. See
`identity/domain/__init__.py` for the layering rule this mirrors."""

from __future__ import annotations

from mnemos.features.chat.domain.events import (
    AssistantDone,
    AssistantError,
    AssistantToken,
    ChatStreamEvent,
)
from mnemos.features.chat.domain.ids import ChatMessageId, ChatSessionId, FolderId
from mnemos.features.chat.domain.models import (
    ChatMessageRecord,
    ChatSessionDetail,
    ChatSessionPage,
    ChatSessionSummary,
    CitationInput,
    CitationRecord,
    FolderRecord,
)

__all__ = [
    "AssistantDone",
    "AssistantError",
    "AssistantToken",
    "ChatMessageId",
    "ChatMessageRecord",
    "ChatSessionDetail",
    "ChatSessionId",
    "ChatSessionPage",
    "ChatSessionSummary",
    "ChatStreamEvent",
    "CitationInput",
    "CitationRecord",
    "FolderId",
    "FolderRecord",
]
