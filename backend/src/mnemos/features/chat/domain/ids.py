"""Typed identifiers for the chat domain. See `identity/domain/ids.py` for why
these are `NewType` rather than bare `UUID` — a transposed `session_id`/`user_id`
in a multi-tenant query is a data leak, not a crash, and the newtype turns it
into a mypy error at the call site."""

from __future__ import annotations

from typing import NewType
from uuid import UUID

ChatSessionId = NewType("ChatSessionId", UUID)
ChatMessageId = NewType("ChatMessageId", UUID)
FolderId = NewType("FolderId", UUID)
BookmarkId = NewType("BookmarkId", UUID)
FeedbackId = NewType("FeedbackId", UUID)
