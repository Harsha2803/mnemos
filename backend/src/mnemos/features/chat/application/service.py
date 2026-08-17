"""The chat use case: session CRUD, and the streamed reply.

`stream_reply` is the one deliverable worth reading closely. **It persists the
user's message before calling the model** — deliverable 2's requirement that a
crashed generation leaves a conversation with a question in it rather than
nothing — and **the assistant message is written only after the stream
completes**, never incrementally. That second choice is what makes an abandoned
stream leave no half-written row: if the caller stops iterating this generator
(a client disconnect, translated by Starlette into cancelling the task that
drives it), execution never reaches the `append_assistant_message` call, because
that call is the last thing in the loop rather than something a `finally`
block tries to run on the way out.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator, Sequence
from datetime import datetime

from mnemos.core.errors import NotFoundError, UpstreamError, ValidationError
from mnemos.core.logging import get_logger
from mnemos.core.types import MessageRole
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.application.titles import (
    DEFAULT_SESSION_TITLE,
    title_session_from_first_message,
)
from mnemos.features.chat.domain import (
    AssistantDone,
    AssistantError,
    AssistantToken,
    ChatMessageRecord,
    ChatSessionDetail,
    ChatSessionId,
    ChatSessionPage,
    ChatSessionSummary,
    ChatStreamEvent,
)
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.llm.domain.model import ChatDone, ChatModel, ChatToken, ChatTurn

log = get_logger(__name__)

#: The default system turn. `C2` replaces this with a versioned, activatable
#: prompt read from the database; until then it is a literal here rather than a
#: half-built prompt store nothing else in this milestone needs.
SYSTEM_PROMPT = (
    "You are Mnemos, an enterprise AI assistant. Answer clearly and concisely. "
    "You are not yet connected to any documents, databases or tools for this "
    "conversation — if the question needs one of those, say so plainly rather "
    "than guessing."
)

DEFAULT_PAGE_SIZE = 20


class ChatService:
    def __init__(
        self,
        *,
        repository: ChatRepository,
        model: ChatModel,
        history_turns: int,
    ) -> None:
        self._repository = repository
        self._model = model
        self._history_turns = history_turns

    async def create_session(
        self, *, org_id: OrgId, user_id: UserId, title: str | None
    ) -> ChatSessionSummary:
        return await self._repository.create_session(
            org_id=org_id, user_id=user_id, title=title or DEFAULT_SESSION_TITLE
        )

    async def list_sessions(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ChatSessionPage:
        before = decode_cursor(cursor) if cursor is not None else None
        # One extra row, never shown, to answer "is there a next page" without
        # a second COUNT query.
        rows = await self._repository.list_sessions(
            org_id=org_id, user_id=user_id, limit=limit + 1, before=before
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1]) if has_more and page else None
        return ChatSessionPage(sessions=tuple(page), next_cursor=next_cursor)

    async def get_session_detail(
        self, *, org_id: OrgId, user_id: UserId, session_id: ChatSessionId
    ) -> ChatSessionDetail:
        session = await self._owned_session(org_id=org_id, user_id=user_id, session_id=session_id)
        messages = await self._repository.list_messages(org_id=org_id, session_id=session_id)
        citations = await self._repository.list_citations(org_id=org_id, session_id=session_id)
        return ChatSessionDetail(
            session=session, messages=tuple(messages), citations=tuple(citations)
        )

    async def rename_session(
        self, *, org_id: OrgId, user_id: UserId, session_id: ChatSessionId, title: str
    ) -> ChatSessionSummary:
        await self._owned_session(org_id=org_id, user_id=user_id, session_id=session_id)
        renamed = await self._repository.rename_session(
            org_id=org_id, session_id=session_id, title=title
        )
        if renamed is None:  # pragma: no cover - vanished between the two calls
            raise NotFoundError(f"chat session {session_id} not found")
        return renamed

    async def delete_session(
        self, *, org_id: OrgId, user_id: UserId, session_id: ChatSessionId
    ) -> None:
        await self._owned_session(org_id=org_id, user_id=user_id, session_id=session_id)
        await self._repository.delete_session(org_id=org_id, session_id=session_id)

    async def stream_reply(
        self, *, org_id: OrgId, user_id: UserId, session_id: ChatSessionId, content: str
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Persist the question, stream the answer, persist it only if it
        finishes. Raises `NotFoundError` before yielding anything if the
        session does not exist or belongs to someone else — the router relies
        on that to answer 404 rather than starting a stream doomed to be empty.
        """
        session = await self._owned_session(org_id=org_id, user_id=user_id, session_id=session_id)
        await self._repository.append_user_message(
            org_id=org_id, session_id=session_id, content=content
        )
        await title_session_from_first_message(
            repository=self._repository, org_id=org_id, session=session, content=content
        )
        history = await self._repository.list_messages(org_id=org_id, session_id=session_id)
        turns = _build_turns(history, history_turns=self._history_turns)

        started = False
        chunks: list[str] = []
        start = time.perf_counter()
        try:
            async for event in self._model.stream(turns):
                if isinstance(event, ChatToken):
                    started = True
                    chunks.append(event.text)
                    if event.text:
                        yield AssistantToken(text=event.text)
                elif isinstance(event, ChatDone):
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    message = await self._repository.append_assistant_message(
                        org_id=org_id,
                        session_id=session_id,
                        content="".join(chunks),
                        prompt_tokens=event.prompt_tokens,
                        completion_tokens=event.completion_tokens,
                        latency_ms=latency_ms,
                        model=self._model.model_name,
                        finish_reason=event.finish_reason,
                    )
                    yield AssistantDone(message=message)
                    return
        except UpstreamError:
            if not started:
                # Nothing has been yielded yet, so the caller (the router,
                # priming this generator before opening the SSE response) sees
                # this as an ordinary exception and can still answer 502.
                raise
            log.warning("chat.upstream_error_mid_stream", session_id=str(session_id))
            yield AssistantError(message="the model is unavailable right now")
            return

    async def _owned_session(
        self, *, org_id: OrgId, user_id: UserId, session_id: ChatSessionId
    ) -> ChatSessionSummary:
        """404, never 403, for "not yours" and "does not exist" alike
        (`AuthorizationError`'s docstring; TRACKER §5 deliverable 3). RLS
        already confines the read to `org_id`; the `user_id` check is the
        second predicate a cross-tenant query cannot express."""
        session = await self._repository.get_session(org_id=org_id, session_id=session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError(f"chat session {session_id} not found")
        return session


def _build_turns(history: Sequence[ChatMessageRecord], *, history_turns: int) -> list[ChatTurn]:
    """System prompt plus the most recent `history_turns` messages, oldest
    first — the shape Ollama's `/api/chat` expects."""
    recent = list(history)[-history_turns:] if history_turns > 0 else list(history)
    turns = [ChatTurn(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT)]
    turns.extend(ChatTurn(role=MessageRole(m.role), content=m.content) for m in recent)
    return turns


def encode_cursor(row: ChatSessionSummary) -> str:
    sort_key = row.last_message_at or row.created_at
    return f"{sort_key.isoformat()}|{row.id}"


def decode_cursor(cursor: str) -> tuple[datetime, ChatSessionId]:
    timestamp, _, raw_id = cursor.rpartition("|")
    if not timestamp or not raw_id:
        raise ValidationError("malformed pagination cursor", field="cursor")
    try:
        return datetime.fromisoformat(timestamp), ChatSessionId(uuid.UUID(raw_id))
    except ValueError as exc:
        raise ValidationError("malformed pagination cursor", field="cursor") from exc
