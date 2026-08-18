"""The RAG flow: retrieve, assemble a prompt, stream an answer, persist citations.

Depends on `features/chat` (persistence, the streaming shape) and
`features/knowledge` (retrieval) — allowed, because the layering rule
(ADAPTATION §5) is `features` must never import `flows`, not the reverse. This
is where that rule earns its keep: `ChatService` and `KnowledgeService` stay
ignorant of each other, and this module is the one place that knows both.

Persistence discipline is identical to `ChatService.stream_reply` (`A1`): the
user's question is persisted before the model is called, and the assistant's
answer — with its citations — is persisted only after the stream completes,
so an abandoned stream leaves no half-written row. The duplication between the
two `stream_reply`s is the cost of the layering rule; it is a page of
straightforward code, not a design flaw to fix by having one import the other.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator

from mnemos.core.errors import NotFoundError, UpstreamError
from mnemos.core.logging import get_logger
from mnemos.core.types import MessageRole, OperatorKind, TrustTier
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.application.titles import title_session_from_first_message
from mnemos.features.chat.domain import (
    AssistantDone,
    AssistantError,
    AssistantToken,
    ChatSessionId,
    ChatStreamEvent,
    CitationInput,
)
from mnemos.features.context.application import ContextService
from mnemos.features.context.domain import ContextCandidate
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.application.service import KnowledgeService
from mnemos.features.knowledge.domain import HeuristicTokenizer
from mnemos.features.llm.domain.model import ChatDone, ChatModel, ChatToken, ChatTurn
from mnemos.flows.rag.domain import (
    RAG_SYSTEM_PROMPT,
    build_context_block,
    extract_citations,
    truncate_to_budget,
)

log = get_logger(__name__)

FLOW_NAME = "rag"


class RagFlow:
    def __init__(
        self,
        *,
        chat_repository: ChatRepository,
        knowledge: KnowledgeService,
        model: ChatModel,
        token_budget: int,
        retrieval_k: int,
        context: ContextService | None = None,
    ) -> None:
        self._chat = chat_repository
        self._knowledge = knowledge
        self._model = model
        self._token_budget = token_budget
        self._retrieval_k = retrieval_k
        self._tokenizer = HeuristicTokenizer()
        self._context = context

    async def stream_reply(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        caller_tags: tuple[str, ...],
        session_id: ChatSessionId,
        content: str,
        router_rationale: str | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        session = await self._chat.get_session(org_id=org_id, session_id=session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError(f"chat session {session_id} not found")

        await self._chat.append_user_message(org_id=org_id, session_id=session_id, content=content)
        await title_session_from_first_message(
            repository=self._chat, org_id=org_id, session=session, content=content
        )

        candidates = await self._knowledge.retrieve(
            org_id=org_id, caller_tags=caller_tags, query=content, k=self._retrieval_k
        )
        chunks = truncate_to_budget(
            list(candidates), self._tokenizer, budget_tokens=self._token_budget
        )
        bundle_id = None
        if self._context is not None:
            context_candidates = [
                ContextCandidate(
                    key=f"chunk:{chunk.chunk_id}",
                    section="documents",
                    operator=(
                        OperatorKind.LEXICAL
                        if "lexical" in chunk.operator_id
                        else OperatorKind.VECTOR
                    ),
                    operator_id=chunk.operator_id,
                    text=chunk.text,
                    tokens=chunk.token_count,
                    raw_score=chunk.score,
                    rrf_score=chunk.score,
                    trust_tier=TrustTier.RETRIEVED,
                    source_kind="document",
                    source_ref=str(chunk.chunk_id),
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    metadata={"page": chunk.page_number},
                )
                for chunk in candidates
            ]
            bundle_id, prompt, admitted = await self._context.compile_and_persist(
                org_id=org_id,
                user_id=user_id,
                caller_tags=caller_tags,
                session_id=session_id,
                flow=FLOW_NAME,
                query=content,
                system_prompt=RAG_SYSTEM_PROMPT,
                token_budget=self._token_budget,
                candidates=context_candidates,
                operator_actuals={
                    "document_retrieval": {
                        "returned": len(candidates),
                        "authorization": "inside vector and lexical scans",
                        "currency": "inside vector and lexical scans",
                    }
                },
            )
            admitted_chunk_ids = {item.chunk_id for item in admitted if item.chunk_id is not None}
            chunks = [chunk for chunk in candidates if chunk.chunk_id in admitted_chunk_ids]
            turns = [ChatTurn(role=MessageRole.SYSTEM, content=prompt)]
        else:
            turns = [
                ChatTurn(role=MessageRole.SYSTEM, content=RAG_SYSTEM_PROMPT),
                ChatTurn(role=MessageRole.SYSTEM, content=build_context_block(chunks)),
                ChatTurn(role=MessageRole.USER, content=content),
            ]

        started = False
        pieces: list[str] = []
        start = time.perf_counter()
        try:
            async for event in self._model.stream(turns):
                if isinstance(event, ChatToken):
                    started = True
                    pieces.append(event.text)
                    if event.text:
                        yield AssistantToken(text=event.text)
                elif isinstance(event, ChatDone):
                    answer = "".join(pieces)
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    message = await self._chat.append_assistant_message(
                        org_id=org_id,
                        session_id=session_id,
                        content=answer,
                        prompt_tokens=event.prompt_tokens,
                        completion_tokens=event.completion_tokens,
                        latency_ms=latency_ms,
                        model=self._model.model_name,
                        finish_reason=event.finish_reason,
                        flow=FLOW_NAME,
                        router_rationale=router_rationale,
                    )
                    targets = extract_citations(answer, chunks)
                    if targets:
                        await self._chat.add_citations(
                            org_id=org_id,
                            message_id=message.id,
                            citations=[
                                CitationInput(
                                    marker=t.marker,
                                    document_id=t.chunk.document_id,
                                    chunk_id=t.chunk.chunk_id,
                                    quoted_text=t.chunk.text,
                                    start_char=t.chunk.char_start,
                                    end_char=t.chunk.char_end,
                                    page_number=t.chunk.page_number,
                                    score=t.chunk.score,
                                )
                                for t in targets
                            ],
                        )
                    if self._context is not None and bundle_id is not None:
                        await self._context.attach(
                            org_id=org_id, message_id=message.id, bundle_id=bundle_id
                        )
                    yield AssistantDone(message=message)
                    return
        except UpstreamError:
            if not started:
                raise
            log.warning("rag.upstream_error_mid_stream", session_id=str(session_id))
            yield AssistantError(message="the model is unavailable right now")
            return
