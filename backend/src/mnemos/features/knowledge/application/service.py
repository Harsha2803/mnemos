"""The knowledge use case: upload → extract → chunk → embed, and retrieval.

**Ingestion runs synchronously in the request handler** (TRACKER §5,
"explicitly not in A2"). `ingest_job`/`ingest_job_event` exist in the schema
(`M2`) but heartbeat, retries and a worker queue are `B2` — honest at demo
scale, and exactly what `B2` replaces with real job tracking rather than a
half-built queue nothing yet drains.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from mnemos.core.errors import NotFoundError
from mnemos.core.logging import get_logger
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.adapters.extraction import extract_pages
from mnemos.features.knowledge.application.ports import KnowledgeRepository, Retriever
from mnemos.features.knowledge.domain import (
    DocumentId,
    DocumentSummary,
    Embedder,
    RetrievedChunk,
    Tokenizer,
    chunk_text,
    deduplicate,
    reciprocal_rank_fusion,
)
from mnemos.platform.objectstore.port import ObjectStore

log = get_logger(__name__)

#: `document.trust_tier`'s own server default — passed explicitly to
#: `chunk_embedding` rows too, so the two stay equal without a second read.
#: Lower is more trusted; an upload is not vouched for by anyone, hence the
#: high (low-trust) default rather than an optimistic one.
DEFAULT_TRUST_TIER = 10
DEFAULT_RETRIEVAL_K = 8
ProgressReporter = Callable[[int, int, str], Awaitable[None]]


class KnowledgeService:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        retriever: Retriever,
        objects: ObjectStore,
        embedder: Embedder,
        tokenizer: Tokenizer,
        rrf_k: int,
        near_duplicate_threshold: float,
    ) -> None:
        self._repository = repository
        self._retriever = retriever
        self._objects = objects
        self._embedder = embedder
        self._tokenizer = tokenizer
        self._rrf_k = rrf_k
        self._near_duplicate_threshold = near_duplicate_threshold

    async def upload_document(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        title: str,
        media_type: str,
        data: bytes,
    ) -> DocumentSummary:
        return await self._ingest(
            org_id=org_id,
            user_id=user_id,
            title=title,
            media_type=media_type,
            data=data,
            source_kind="local_fs",
            source_uri=None,
            trust_tier=DEFAULT_TRUST_TIER,
        )

    async def ingest_connector_item(
        self,
        *,
        org_id: OrgId,
        title: str,
        media_type: str,
        data: bytes,
        source_kind: str,
        source_uri: str,
        trust_tier: int,
        progress: ProgressReporter | None = None,
    ) -> DocumentSummary:
        """The worker's entry point (`B1` deliverable 4) — same body as
        `upload_document`, reused rather than duplicated, parametrized by the
        connector's own kind/uri instead of the object-store key and no
        `user_id` (nobody is signed in; the row this produces has
        `uploaded_by = NULL`, same as any other system-originated write).

        `trust_tier` is the caller's decision, not this method's: `Threat
        Model.md` §4's "external connectors ≥ 4" rule was written against
        `_v1/core.py`'s retired 0-6 scale, and `core/types.py`'s current
        4-rung `TrustTier` has no member below `RETRIEVED` (10) — already
        the floor, and already what a manual upload gets. Connector content
        is not more trusted than an upload, and the schema cannot express
        less; `TRACKER.md`'s `B1` deliverable 1 note records this
        reconciliation, so callers pass `TrustTier.RETRIEVED` rather than a
        new constant invented here.
        """
        return await self._ingest(
            org_id=org_id,
            user_id=None,
            title=title,
            media_type=media_type,
            data=data,
            source_kind=source_kind,
            source_uri=source_uri,
            trust_tier=trust_tier,
            progress=progress,
        )

    async def _ingest(
        self,
        *,
        org_id: OrgId,
        user_id: UserId | None,
        title: str,
        media_type: str,
        data: bytes,
        source_kind: str,
        source_uri: str | None,
        trust_tier: int,
        progress: ProgressReporter | None = None,
    ) -> DocumentSummary:
        total_units = 4
        content_sha256 = hashlib.sha256(data).hexdigest()
        existing = await self._repository.find_by_content_hash(
            org_id=org_id, content_sha256=content_sha256
        )
        if existing is not None:
            log.info("knowledge.upload_deduplicated", document_id=str(existing.id))
            if progress is not None:
                await progress(
                    total_units, total_units, "deduplicated against an existing document"
                )
            return existing

        object_key = f"{org_id}/{content_sha256}"
        await self._objects.put(object_key, data, content_type=media_type)
        if progress is not None:
            await progress(1, total_units, "stored source bytes")

        document = await self._repository.create_document(
            org_id=org_id,
            user_id=user_id,
            title=title,
            media_type=media_type,
            byte_size=len(data),
            content_sha256=content_sha256,
            source_kind=source_kind,
            source_uri=source_uri or object_key,
            object_key=object_key,
        )
        if progress is not None:
            await progress(2, total_units, "created document record")

        pages = await extract_pages(data, media_type)
        raw_chunks = []
        ordinal = 0
        offset = 0
        for page_number, text in pages:
            for c in chunk_text(text, self._tokenizer, page=page_number):
                c.ordinal = ordinal
                c.char_start += offset
                c.char_end += offset
                raw_chunks.append(c)
                ordinal += 1
            offset += len(text)
        if progress is not None:
            await progress(3, total_units, f"prepared {len(raw_chunks)} chunks")

        if raw_chunks:
            vectors = self._embedder.encode([c.content for c in raw_chunks])
            await self._repository.add_chunks(
                org_id=org_id,
                document_id=document.id,
                raw_chunks=raw_chunks,
                vectors=vectors,
                model_name=self._embedder.name,
                acl_tag_ids=[],
                trust_tier=trust_tier,
            )
        if progress is not None:
            await progress(total_units, total_units, "stored chunk embeddings")
        detail = await self._repository.get_document(org_id=org_id, document_id=document.id)
        if detail is None:  # pragma: no cover - written immediately above
            raise NotFoundError(f"document {document.id} vanished mid-ingest")
        return detail

    async def list_documents(self, *, org_id: OrgId) -> Sequence[DocumentSummary]:
        return await self._repository.list_documents(org_id=org_id)

    async def get_document(self, *, org_id: OrgId, document_id: DocumentId) -> DocumentSummary:
        summary = await self._repository.get_document(org_id=org_id, document_id=document_id)
        if summary is None:
            raise NotFoundError(f"document {document_id} not found")
        return summary

    async def delete_document(self, *, org_id: OrgId, document_id: DocumentId) -> None:
        object_key = await self._repository.delete_document(org_id=org_id, document_id=document_id)
        if object_key is None:
            raise NotFoundError(f"document {document_id} not found")
        await self._objects.delete(object_key)

    async def mark_superseded(
        self, *, org_id: OrgId, old_document_id: DocumentId, new_document_id: DocumentId
    ) -> None:
        await self._repository.mark_superseded(
            org_id=org_id, old_document_id=old_document_id, new_document_id=new_document_id
        )

    async def retrieve(
        self,
        *,
        org_id: OrgId,
        caller_tags: Sequence[str],
        query: str,
        k: int = DEFAULT_RETRIEVAL_K,
    ) -> list[RetrievedChunk]:
        """Vector + lexical, fused by RRF, near-duplicates removed. Returns
        fused-score order; the caller (the RAG flow) truncates to its own
        token budget, because how much of this to spend is a chat-flow
        decision, not a retrieval one."""
        caller_tag_ids: list[UUID] = list(
            await self._repository.resolve_tag_ids(org_id=org_id, slugs=caller_tags)
        )
        query_vector = self._embedder.encode([query])[0]

        vector_results = await self._retriever.vector_search(
            org_id=org_id, caller_tag_ids=caller_tag_ids, query_vector=query_vector, k=k
        )
        lexical_results = await self._retriever.lexical_search(
            org_id=org_id, caller_tag_ids=caller_tag_ids, query_text=query, k=k
        )

        fused = reciprocal_rank_fusion([vector_results, lexical_results], k=self._rrf_k)
        deduped, _report = deduplicate(fused, threshold=self._near_duplicate_threshold)
        return [item.chunk for item in deduped]
