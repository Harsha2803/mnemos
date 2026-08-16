"""What `KnowledgeService` needs from persistence and retrieval, as `Protocol`s
— the adapters satisfy these structurally, matching `features/chat`'s pattern."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

import numpy as np

from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.domain import DocumentId, DocumentSummary, RawChunk, RetrievedChunk


class KnowledgeRepository(Protocol):
    async def resolve_tag_ids(self, *, org_id: OrgId, slugs: Sequence[str]) -> list[UUID]: ...

    async def find_by_content_hash(
        self, *, org_id: OrgId, content_sha256: str
    ) -> DocumentSummary | None: ...

    async def create_document(
        self,
        *,
        org_id: OrgId,
        user_id: UserId | None,
        title: str,
        media_type: str,
        byte_size: int,
        content_sha256: str,
        source_kind: str,
        source_uri: str,
        object_key: str,
    ) -> DocumentSummary: ...

    async def add_chunks(
        self,
        *,
        org_id: OrgId,
        document_id: DocumentId,
        raw_chunks: Sequence[RawChunk],
        vectors: np.ndarray,
        model_name: str,
        acl_tag_ids: Sequence[UUID],
        trust_tier: int,
    ) -> None: ...

    async def list_documents(self, *, org_id: OrgId) -> Sequence[DocumentSummary]: ...

    async def get_document(
        self, *, org_id: OrgId, document_id: DocumentId
    ) -> DocumentSummary | None: ...

    async def delete_document(self, *, org_id: OrgId, document_id: DocumentId) -> str | None: ...

    async def mark_superseded(
        self, *, org_id: OrgId, old_document_id: DocumentId, new_document_id: DocumentId
    ) -> None: ...


class Retriever(Protocol):
    async def vector_search(
        self,
        *,
        org_id: OrgId,
        caller_tag_ids: Sequence[UUID],
        query_vector: np.ndarray,
        k: int,
    ) -> list[RetrievedChunk]: ...

    async def lexical_search(
        self,
        *,
        org_id: OrgId,
        caller_tag_ids: Sequence[UUID],
        query_text: str,
        k: int,
    ) -> list[RetrievedChunk]: ...
