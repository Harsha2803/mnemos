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

from sqlalchemy import delete, exists, func, literal, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from mnemos.core.ids import IdGenerator
from mnemos.core.types import MessageRole
from mnemos.features.chat.adapters.models import (
    Bookmark,
    ChatMessage,
    ChatSession,
    Folder,
    MessageCitation,
)
from mnemos.features.chat.application.ports import UNSET, _UnsetType
from mnemos.features.chat.domain import (
    BookmarkedMessage,
    BookmarkId,
    BookmarkRecord,
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
        self,
        *,
        org_id: OrgId,
        session_id: ChatSessionId,
        title: str | None = None,
        folder_id: FolderId | _UnsetType | None = UNSET,
    ) -> ChatSessionSummary | None:
        values: dict[str, object] = {}
        if title is not None:
            values["title"] = title
        if not isinstance(folder_id, _UnsetType):
            values["folder_id"] = folder_id
        async with self._db.session(org_id=org_id) as session:
            if values:
                row = await session.scalar(
                    update(ChatSession)
                    .where(ChatSession.org_id == org_id, ChatSession.id == session_id)
                    .values(**values)
                    .returning(ChatSession)
                )
            else:
                row = await session.scalar(
                    select(ChatSession).where(
                        ChatSession.org_id == org_id, ChatSession.id == session_id
                    )
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

    async def list_messages_with_state(
        self, *, org_id: OrgId, session_id: ChatSessionId, user_id: UserId
    ) -> Sequence[ChatMessageRecord]:
        bookmarked_expr = exists(
            select(Bookmark.id).where(
                Bookmark.message_id == ChatMessage.id, Bookmark.user_id == user_id
            )
        )
        query = (
            select(ChatMessage, bookmarked_expr)
            .where(ChatMessage.org_id == org_id, ChatMessage.session_id == session_id)
            .order_by(ChatMessage.ordinal.asc())
        )
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.execute(query)).all()
        return [_message_record(row[0], bookmarked=row[1]) for row in rows]

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

    async def create_folder(self, *, org_id: OrgId, user_id: UserId, name: str) -> FolderRecord:
        new_id = self._ids.new()
        async with self._db.session(org_id=org_id) as session:
            row = Folder(id=new_id, org_id=org_id, user_id=user_id, name=name)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _folder_record(row, session_count=0)

    async def list_folders(self, *, org_id: OrgId, user_id: UserId) -> Sequence[FolderRecord]:
        session_count = (
            select(func.count(ChatSession.id))
            .where(
                ChatSession.folder_id == Folder.id,
                ChatSession.org_id == org_id,
                ChatSession.deleted_at.is_(None),
            )
            .scalar_subquery()
        )
        query = (
            select(Folder, session_count)
            .where(Folder.org_id == org_id, Folder.user_id == user_id)
            .order_by(Folder.position.asc(), Folder.id.asc())
        )
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.execute(query)).all()
        return [_folder_record(folder, session_count=count) for folder, count in rows]

    async def get_folder(
        self, *, org_id: OrgId, user_id: UserId, folder_id: FolderId
    ) -> FolderRecord | None:
        session_count = (
            select(func.count(ChatSession.id))
            .where(
                ChatSession.folder_id == folder_id,
                ChatSession.org_id == org_id,
                ChatSession.deleted_at.is_(None),
            )
            .scalar_subquery()
        )
        async with self._db.session(org_id=org_id) as session:
            row = (
                await session.execute(
                    select(Folder, session_count).where(
                        Folder.org_id == org_id,
                        Folder.user_id == user_id,
                        Folder.id == folder_id,
                    )
                )
            ).first()
        return _folder_record(row[0], session_count=row[1]) if row is not None else None

    async def rename_folder(
        self, *, org_id: OrgId, folder_id: FolderId, name: str | None, position: int | None
    ) -> FolderRecord | None:
        values: dict[str, object] = {}
        if name is not None:
            values["name"] = name
        if position is not None:
            values["position"] = position
        session_count_query = select(func.count(ChatSession.id)).where(
            ChatSession.folder_id == folder_id,
            ChatSession.org_id == org_id,
            ChatSession.deleted_at.is_(None),
        )
        async with self._db.session(org_id=org_id) as session:
            if values:
                row = await session.scalar(
                    update(Folder)
                    .where(Folder.org_id == org_id, Folder.id == folder_id)
                    .values(**values)
                    .returning(Folder)
                )
            else:
                row = await session.scalar(
                    select(Folder).where(Folder.org_id == org_id, Folder.id == folder_id)
                )
            if row is None:
                return None
            count = await session.scalar(session_count_query)
        return _folder_record(row, session_count=count or 0)

    async def delete_folder(self, *, org_id: OrgId, folder_id: FolderId) -> bool:
        # `chat_session.folder_id` is `ondelete=SET NULL`, so this un-files the
        # folder's sessions at the database level with no extra query.
        async with self._db.session(org_id=org_id) as session:
            deleted = await session.scalar(
                delete(Folder)
                .where(Folder.org_id == org_id, Folder.id == folder_id)
                .returning(Folder.id)
            )
        return deleted is not None

    async def upsert_bookmark(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId, note: str | None
    ) -> BookmarkRecord | None:
        async with self._db.session(org_id=org_id) as session:
            owned = await session.scalar(
                select(ChatMessage.id)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(
                    ChatMessage.id == message_id,
                    ChatMessage.org_id == org_id,
                    ChatSession.user_id == user_id,
                )
            )
            if owned is None:
                return None
            statement = insert(Bookmark).values(
                id=self._ids.new(),
                org_id=org_id,
                user_id=user_id,
                message_id=message_id,
                note=note,
            )
            row = await session.scalar(
                statement.on_conflict_do_update(
                    constraint="uq_bookmark_user_id_message_id",
                    set_={"note": statement.excluded.note, "updated_at": func.now()},
                ).returning(Bookmark)
            )
        return _bookmark_record(row) if row is not None else None

    async def remove_bookmark(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId
    ) -> bool:
        async with self._db.session(org_id=org_id) as session:
            deleted = await session.scalar(
                delete(Bookmark)
                .where(
                    Bookmark.org_id == org_id,
                    Bookmark.user_id == user_id,
                    Bookmark.message_id == message_id,
                )
                .returning(Bookmark.id)
            )
        return deleted is not None

    async def list_bookmarks(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        limit: int,
        before: tuple[datetime, BookmarkId] | None,
    ) -> Sequence[BookmarkedMessage]:
        query = (
            select(Bookmark, ChatMessage, ChatSession)
            .join(ChatMessage, ChatMessage.id == Bookmark.message_id)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(Bookmark.org_id == org_id, Bookmark.user_id == user_id)
            .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
            .limit(limit)
        )
        if before is not None:
            before_ts, before_id = before
            query = query.where(
                tuple_(Bookmark.created_at, Bookmark.id)
                < tuple_(literal(before_ts), literal(before_id))
            )
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.execute(query)).all()
        return [
            BookmarkedMessage(
                bookmark=_bookmark_record(bookmark),
                message_content=message.content,
                message_role=MessageRole(message.role),
                session_id=ChatSessionId(session_row.id),
                session_title=session_row.title,
            )
            for bookmark, message, session_row in rows
        ]

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
        folder_id=FolderId(row.folder_id) if row.folder_id is not None else None,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _folder_record(row: Folder, *, session_count: int) -> FolderRecord:
    return FolderRecord(
        id=FolderId(row.id),
        org_id=OrgId(row.org_id),
        user_id=UserId(row.user_id),
        name=row.name,
        position=row.position,
        session_count=session_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _message_record(row: ChatMessage, *, bookmarked: bool = False) -> ChatMessageRecord:
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
        bookmarked=bookmarked,
    )


def _bookmark_record(row: Bookmark) -> BookmarkRecord:
    return BookmarkRecord(
        id=BookmarkId(row.id),
        org_id=OrgId(row.org_id),
        user_id=UserId(row.user_id),
        message_id=ChatMessageId(row.message_id),
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
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
