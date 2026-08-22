"""Chat domain: pure types, no SQLAlchemy, no FastAPI, no I/O. See
`identity/domain/__init__.py` for the layering rule this mirrors."""

from __future__ import annotations

from mnemos.features.chat.domain.events import (
    AssistantDone,
    AssistantError,
    AssistantToken,
    ChatStreamEvent,
)
from mnemos.features.chat.domain.ids import (
    BookmarkId,
    ChatMessageId,
    ChatSessionId,
    FeedbackId,
    FolderId,
)
from mnemos.features.chat.domain.models import (
    BookmarkedMessage,
    BookmarkPage,
    BookmarkRecord,
    ChatMessageRecord,
    ChatSessionDetail,
    ChatSessionPage,
    ChatSessionSummary,
    CitationInput,
    CitationRecord,
    FeedbackRecord,
    FolderRecord,
)

__all__ = [
    "AssistantDone",
    "AssistantError",
    "AssistantToken",
    "BookmarkId",
    "BookmarkPage",
    "BookmarkRecord",
    "BookmarkedMessage",
    "ChatMessageId",
    "ChatMessageRecord",
    "ChatSessionDetail",
    "ChatSessionId",
    "ChatSessionPage",
    "ChatSessionSummary",
    "ChatStreamEvent",
    "CitationInput",
    "CitationRecord",
    "FeedbackId",
    "FeedbackRecord",
    "FolderId",
    "FolderRecord",
]
