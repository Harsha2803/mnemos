"""`ChatRepository` over Postgres.

Every statement runs inside `Database.session(org_id=...)`, so `app.current_org`
is bound for the transaction and row-level security applies underneath the
explicit `org_id` predicate (CodingStandards §6) — the same discipline
`identity/adapters/sessions.py` documents at length.

**Message insertion computes its own ordinal**, via `INSERT ... SELECT` against
`MAX(ordinal)` in the same statement, so the read and the write cannot be split
by a concurrent sender the way a separate `SELECT` then `INSERT` could be. The
`(session_id, ordinal)` unique constraint is the backstop if two genuinely
concurrent sends still collide.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, literal, select, tuple_, update

from mnemos.core.ids import IdGenerator
from mnemos.core.types import MessageRole
from mnemos.features.chat.adapters.models import ChatMessage, ChatSession, MessageCitation
from mnemos.features.chat.domain import (
    ChatMessageId,
    ChatMessageRecord,
    ChatSessionId,
    ChatSessionSummary,
    CitationInput,
    CitationRecord,
)
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.platform.db import Database


class SqlChatRepository:
    """`ChatRepository` over Postgres."""

    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def create_session(
        self, *, org_id: OrgId, user_id: UserId, title: str
    ) -> ChatSessionSummary:
        new_id = self._ids.new()
        async with self._db.session(org_id=org_id) as session:
            row = ChatSession(id=new_id, org_id=org_id, user_id=user_id, title=title)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _session_summary(row)

    async def list_sessions(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        limit: int,
        before: tuple[datetime, ChatSessionId] | None,
    ) -> Sequence[ChatSessionSummary]:
        sort_key = func.coalesce(ChatSession.last_message_at, ChatSession.created_at)
        query = (
            select(ChatSession)
            .where(
                ChatSession.org_id == org_id,
                ChatSession.user_id == user_id,
                ChatSession.deleted_at.is_(None),
            )
            .order_by(sort_key.desc(), ChatSession.id.desc())
            .limit(limit)
        )
        if before is not None:
            before_ts, before_id = before
            query = query.where(
                tuple_(sort_key, ChatSession.id) < tuple_(literal(before_ts), literal(before_id))
            )
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.scalars(query)).all()
        return [_session_summary(r) for r in rows]

    async def get_session(
        self, *, org_id: OrgId, session_id: ChatSessionId
    ) -> ChatSessionSummary | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(ChatSession).where(
                    ChatSession.org_id == org_id,
                    ChatSession.id == session_id,
                    ChatSession.deleted_at.is_(None),
                )
            )
        return _session_summary(row) if row is not None else None

    async def rename_session(
        self, *, org_id: OrgId, session_id: ChatSessionId, title: str
    ) -> ChatSessionSummary | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                update(ChatSession)
                .where(ChatSession.org_id == org_id, ChatSession.id == session_id)
                .values(title=title)
                .returning(ChatSession)
            )
        return _session_summary(row) if row is not None else None

    async def delete_session(self, *, org_id: OrgId, session_id: ChatSessionId) -> bool:
        async with self._db.session(org_id=org_id) as session:
            claimed = await session.scalar(
                update(ChatSession)
                .where(
                    ChatSession.org_id == org_id,
                    ChatSession.id == session_id,
                    ChatSession.deleted_at.is_(None),
                )
                .values(deleted_at=func.now())
                .returning(ChatSession.id)
            )
        return claimed is not None

    async def list_messages(
        self, *, org_id: OrgId, session_id: ChatSessionId
    ) -> Sequence[ChatMessageRecord]:
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.org_id == org_id, ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.ordinal.asc())
                )
            ).all()
        return [_message_record(r) for r in rows]

    async def append_user_message(
        self, *, org_id: OrgId, session_id: ChatSessionId, content: str
    ) -> ChatMessageRecord:
        return await self._append_message(
            org_id=org_id, session_id=session_id, role=MessageRole.USER, content=content
        )

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
    ) -> ChatMessageRecord:
        return await self._append_message(
            org_id=org_id,
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            model=model,
            finish_reason=finish_reason,
            flow=flow,
            router_rationale=router_rationale,
        )

    async def add_citations(
        self, *, org_id: OrgId, message_id: ChatMessageId, citations: Sequence[CitationInput]
    ) -> None:
        async with self._db.session(org_id=org_id) as session:
            for citation in citations:
                session.add(
                    MessageCitation(
                        id=self._ids.new(),
                        org_id=org_id,
                        message_id=message_id,
                        marker=citation.marker,
                        document_id=citation.document_id,
                        chunk_id=citation.chunk_id,
                        quoted_text=citation.quoted_text,
                        start_char=citation.start_char,
                        end_char=citation.end_char,
                        page_number=citation.page_number,
                        score=citation.score,
                    )
                )

    async def list_citations(
        self, *, org_id: OrgId, session_id: ChatSessionId
    ) -> Sequence[CitationRecord]:
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(MessageCitation)
                    .join(ChatMessage, ChatMessage.id == MessageCitation.message_id)
                    .where(MessageCitation.org_id == org_id, ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.ordinal.asc(), MessageCitation.marker.asc())
                )
            ).all()
        return [_citation_record(r) for r in rows]

    async def _append_message(
        self,
        *,
        org_id: OrgId,
        session_id: ChatSessionId,
        role: MessageRole,
        content: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
        flow: str | None = None,
        router_rationale: str | None = None,
    ) -> ChatMessageRecord:
        new_id = self._ids.new()
        next_ordinal = (
            select(func.coalesce(func.max(ChatMessage.ordinal), -1) + 1)
            .where(ChatMessage.org_id == org_id, ChatMessage.session_id == session_id)
            .scalar_subquery()
        )
        async with self._db.session(org_id=org_id) as session:
            row = ChatMessage(
                id=new_id,
                org_id=org_id,
                session_id=session_id,
                ordinal=next_ordinal,
                role=role.value,
                content=content,
                flow=flow,
                router_rationale=router_rationale,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                model=model,
                finish_reason=finish_reason,
            )
            session.add(row)
            await session.flush()
            await session.execute(
                update(ChatSession)
                .where(ChatSession.org_id == org_id, ChatSession.id == session_id)
                .values(last_message_at=func.now())
            )
            await session.refresh(row)
            return _message_record(row)


def _session_summary(row: ChatSession) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=ChatSessionId(row.id),
        org_id=OrgId(row.org_id),
        user_id=UserId(row.user_id),
        title=row.title,
        is_archived=row.is_archived,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _message_record(row: ChatMessage) -> ChatMessageRecord:
    return ChatMessageRecord(
        id=ChatMessageId(row.id),
        session_id=ChatSessionId(row.session_id),
        ordinal=row.ordinal,
        role=MessageRole(row.role),
        content=row.content,
        flow=row.flow,
        router_rationale=row.router_rationale,
        bundle_id=row.bundle_id,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        latency_ms=row.latency_ms,
        model=row.model,
        finish_reason=row.finish_reason,
        error_code=row.error_code,
        created_at=row.created_at,
    )


def _citation_record(row: MessageCitation) -> CitationRecord:
    return CitationRecord(
        id=row.id,
        message_id=ChatMessageId(row.message_id),
        marker=row.marker,
        document_id=row.document_id,
        chunk_id=row.chunk_id,
        quoted_text=row.quoted_text,
        start_char=row.start_char,
        end_char=row.end_char,
        page_number=row.page_number,
        score=row.score,
    )
