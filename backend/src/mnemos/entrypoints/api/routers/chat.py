"""Chat routes: session CRUD, and the SSE endpoint that streams a reply.

Authenticated by doing nothing (`entrypoints/api/security.py`) — nothing here
declares a guard or appears in `public_route_paths`.

**The streaming handler primes the generator before returning a
`StreamingResponse`.** `ChatService.stream_reply` raises `NotFoundError` or
`UpstreamError` *before yielding anything* if the session does not exist, is not
the caller's, or the model cannot be reached at all — and awaiting one
`__anext__()` outside the response lets that exception reach
`handle_domain_error` as an ordinary 404 or 502 rather than a truncated SSE
stream with no status line to carry it. Once the first event exists, the
`StreamingResponse` has committed to 200 and any failure after that point
becomes an `error` SSE frame instead (`ChatService`'s job, not this module's).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.chat.application.service import ChatService
from mnemos.features.chat.domain import (
    AssistantDone,
    AssistantError,
    AssistantToken,
    ChatMessageRecord,
    ChatSessionId,
    ChatSessionSummary,
    CitationRecord,
)
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.flows.nl2sql.application import Nl2SqlFlow
from mnemos.flows.rag.application import RagFlow

router = APIRouter(prefix="/chat", tags=["chat"])

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ChatSessionResponse(BaseModel):
    id: str
    title: str
    is_archived: bool
    last_message_at: str | None
    created_at: str
    updated_at: str


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse]
    next_cursor: str | None


class ChatMessageResponse(BaseModel):
    id: str
    ordinal: int
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    flow: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int | None
    model: str | None
    finish_reason: str | None
    created_at: str


class CitationResponse(BaseModel):
    id: str
    message_id: str
    marker: int
    document_id: str | None
    chunk_id: str | None
    quoted_text: str
    start_char: int | None
    end_char: int | None
    page_number: int | None
    score: float | None


class ChatSessionDetailResponse(BaseModel):
    session: ChatSessionResponse
    messages: list[ChatMessageResponse]
    citations: list[CitationResponse]


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)
    #: Manual for now — `A4`'s classifier replaces both this and
    #: `use_datasource` with real routing (TRACKER §5 deliverable 5's
    #: explicit, written-down provisionality).
    use_documents: bool = False
    #: Same provisionality, for `A3`'s NL2SQL flow. There is exactly one
    #: registered datasource in this build (no registry UI — TRACKER §5,
    #: "explicitly not in A3"), so this selects *that one*, not a specific
    #: slug.
    use_datasource: bool = False


def _session_response(summary: ChatSessionSummary) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=str(summary.id),
        title=summary.title,
        is_archived=summary.is_archived,
        last_message_at=summary.last_message_at.isoformat()
        if summary.last_message_at is not None
        else None,
        created_at=summary.created_at.isoformat(),
        updated_at=summary.updated_at.isoformat(),
    )


def _message_response(record: ChatMessageRecord) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=str(record.id),
        ordinal=record.ordinal,
        role=record.role.value,
        content=record.content,
        flow=record.flow,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        latency_ms=record.latency_ms,
        model=record.model,
        finish_reason=record.finish_reason,
        created_at=record.created_at.isoformat(),
    )


def _citation_response(record: CitationRecord) -> CitationResponse:
    return CitationResponse(
        id=str(record.id),
        message_id=str(record.message_id),
        marker=record.marker,
        document_id=str(record.document_id) if record.document_id else None,
        chunk_id=str(record.chunk_id) if record.chunk_id else None,
        quoted_text=record.quoted_text,
        start_char=record.start_char,
        end_char=record.end_char,
        page_number=record.page_number,
        score=record.score,
    )


def _service(request: Request) -> ChatService:
    service = getattr(request.app.state, "chat_service", None)
    if not isinstance(service, ChatService):  # pragma: no cover - the lifespan sets it
        msg = "chat service is not configured"
        raise RuntimeError(msg)
    return service


def _rag(request: Request) -> RagFlow:
    flow = getattr(request.app.state, "rag_flow", None)
    if not isinstance(flow, RagFlow):  # pragma: no cover - the lifespan sets it
        msg = "the RAG flow is not configured"
        raise RuntimeError(msg)
    return flow


def _nl2sql(request: Request) -> Nl2SqlFlow:
    flow = getattr(request.app.state, "nl2sql_flow", None)
    if not isinstance(flow, Nl2SqlFlow):  # pragma: no cover - the lifespan sets it
        msg = "the NL2SQL flow is not configured"
        raise RuntimeError(msg)
    return flow


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ChatService, Depends(_service)],
) -> ChatSessionResponse:
    summary = await service.create_session(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        title=body.title,
    )
    return _session_response(summary)


@router.get("/sessions")
async def list_sessions(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ChatService, Depends(_service)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> ChatSessionListResponse:
    page = await service.list_sessions(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        limit=limit,
        cursor=cursor,
    )
    return ChatSessionListResponse(
        sessions=[_session_response(s) for s in page.sessions],
        next_cursor=page.next_cursor,
    )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ChatService, Depends(_service)],
) -> ChatSessionDetailResponse:
    detail = await service.get_session_detail(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        session_id=_parse_session_id(session_id),
    )
    return ChatSessionDetailResponse(
        session=_session_response(detail.session),
        messages=[_message_response(m) for m in detail.messages],
        citations=[_citation_response(c) for c in detail.citations],
    )


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ChatService, Depends(_service)],
) -> ChatSessionResponse:
    summary = await service.rename_session(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        session_id=_parse_session_id(session_id),
        title=body.title,
    )
    return _session_response(summary)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ChatService, Depends(_service)],
) -> None:
    await service.delete_session(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        session_id=_parse_session_id(session_id),
    )


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[ChatService, Depends(_service)],
    rag: Annotated[RagFlow, Depends(_rag)],
    nl2sql: Annotated[Nl2SqlFlow, Depends(_nl2sql)],
) -> StreamingResponse:
    if body.use_documents and body.use_datasource:
        raise ValidationError(
            "use_documents and use_datasource are mutually exclusive until A4's router "
            "can combine flows",
            field="use_datasource",
        )
    if body.use_datasource:
        events = nl2sql.stream_reply(
            org_id=caller.principal.org_id,
            user_id=caller.principal.principal_id,
            session_id=_parse_session_id(session_id),
            content=body.content,
        )
    elif body.use_documents:
        events = rag.stream_reply(
            org_id=caller.principal.org_id,
            user_id=caller.principal.principal_id,
            caller_tags=tuple(caller.principal.tags.slugs),
            session_id=_parse_session_id(session_id),
            content=body.content,
        )
    else:
        events = service.stream_reply(
            org_id=caller.principal.org_id,
            user_id=caller.principal.principal_id,
            session_id=_parse_session_id(session_id),
            content=body.content,
        )
    # Priming: the first `__anext__()` runs everything up to (and possibly
    # past) the first token — session lookup, persisting the user's message,
    # opening the model connection. A failure there is still an ordinary
    # exception here, so it reaches `handle_domain_error` as 404 or 502
    # instead of a stream that opened and then silently died.
    try:
        first = await anext(events, None)
    except Exception:
        await events.aclose()
        raise

    async def body_stream() -> AsyncIterator[bytes]:
        try:
            if first is not None:
                yield _sse_frame(first)
            async for event in events:
                yield _sse_frame(event)
        finally:
            await events.aclose()

    return StreamingResponse(
        body_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse_frame(event: AssistantToken | AssistantDone | AssistantError) -> bytes:
    name, payload = _event_payload(event)
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


def _event_payload(
    event: AssistantToken | AssistantDone | AssistantError,
) -> tuple[str, dict[str, Any]]:
    if isinstance(event, AssistantToken):
        return "token", {"text": event.text}
    if isinstance(event, AssistantDone):
        payload: dict[str, Any] = {"message": _message_response(event.message).model_dump()}
        if event.extra is not None:
            # `flows/nl2sql`'s SQL/verdict/rows payload — see `AssistantDone.extra`'s
            # docstring for why it rides the terminal frame instead of a refetch.
            payload["nl2sql"] = event.extra
        return "done", payload
    return "error", {"message": event.message}


def _parse_session_id(raw: str) -> ChatSessionId:
    try:
        return ChatSessionId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError(f"chat session {raw} not found") from exc
