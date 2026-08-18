"""Compile, persist, attach, and replay context artifacts."""

from __future__ import annotations

import time

from mnemos.core.clock import Clock
from mnemos.core.types import JsonValue, OperatorKind, TrustTier
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.domain import ChatMessageId, ChatSessionId
from mnemos.features.context.application.compiler import compile_context
from mnemos.features.context.application.ports import ContextRepository
from mnemos.features.context.domain import (
    AttachBundleCommand,
    ContextBundleId,
    ContextBundleSummary,
    ContextCandidate,
    PersistContextCommand,
)
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.domain import Tokenizer
from mnemos.features.memory.application import MemoryService


class ContextService:
    def __init__(
        self,
        *,
        repository: ContextRepository,
        chat: ChatRepository,
        memory: MemoryService,
        tokenizer: Tokenizer,
        clock: Clock,
        utility_decay_tau: float,
        history_turns: int,
        embedder_name: str,
        operator_deadline_ms: int,
    ) -> None:
        self._repository = repository
        self._chat = chat
        self._memory = memory
        self._tokenizer = tokenizer
        self._clock = clock
        self._utility_decay_tau = utility_decay_tau
        self._history_turns = history_turns
        self._embedder_name = embedder_name
        self._operator_deadline_ms = operator_deadline_ms

    async def compile_and_persist(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        caller_tags: tuple[str, ...],
        session_id: ChatSessionId,
        flow: str,
        query: str,
        system_prompt: str,
        token_budget: int,
        candidates: list[ContextCandidate] | None = None,
        operator_actuals: dict[str, JsonValue] | None = None,
    ) -> tuple[ContextBundleId, str, tuple[ContextCandidate, ...]]:
        started = time.perf_counter()
        pool = list(candidates or [])
        now = self._clock.now()

        memory = await self._memory.history(
            org_id=org_id,
            caller_tags=caller_tags,
            as_of=now,
            believed_at=now,
            include_retracted=False,
        )
        for record in memory.claims:
            text = f"{record.subject.display_name} {record.predicate}: {record.object_text}"
            pool.append(
                ContextCandidate(
                    key=f"memory:{record.id}",
                    section="memory",
                    operator=OperatorKind.MEMORY,
                    operator_id="memory_scan",
                    text=text,
                    tokens=self._tokenizer.count(text),
                    raw_score=record.confidence,
                    rrf_score=record.confidence,
                    trust_tier=record.trust_tier,
                    source_kind="memory",
                    source_ref=str(record.id),
                    memory_id=record.id,
                    metadata={
                        "subject_ref": record.subject.external_ref,
                        "predicate": record.predicate,
                        "recorded_at": record.recorded_at.isoformat(),
                        "valid_from": record.valid_from.isoformat(),
                        "valid_to": record.valid_to.isoformat(),
                    },
                )
            )

        history = list(await self._chat.list_messages(org_id=org_id, session_id=session_id))
        if history and history[-1].role.value == "user" and history[-1].content == query:
            history.pop()
        for rank, message in enumerate(history[-self._history_turns :]):
            text = f"{message.role.value}: {message.content}"
            pool.append(
                ContextCandidate(
                    key=f"history:{message.id}",
                    section="history",
                    operator=OperatorKind.HISTORY,
                    operator_id="history_scan",
                    text=text,
                    tokens=self._tokenizer.count(text),
                    raw_score=1.0 / (rank + 1),
                    rrf_score=1.0 / (rank + 1),
                    trust_tier=TrustTier.USER,
                    source_kind="history",
                    source_ref=str(message.id),
                )
            )

        actuals: dict[str, JsonValue] = {
            "memory_scan": {"returned": len(memory.claims), "acl": "inside_scan"},
            "history_scan": {"returned": len(history[-self._history_turns :])},
            **(operator_actuals or {}),
        }
        compiled = compile_context(
            query=query,
            system_prompt=system_prompt,
            candidates=pool,
            token_budget=token_budget,
            tokenizer=self._tokenizer,
            utility_decay_tau=self._utility_decay_tau,
            operator_actuals=actuals,
        )
        compile_ms = int((time.perf_counter() - started) * 1000)
        bundle_id = await self._repository.persist(
            PersistContextCommand(
                org_id=org_id,
                user_id=user_id,
                session_id=session_id,
                flow=flow,
                query=query,
                deadline_ms=self._operator_deadline_ms,
                compile_ms=compile_ms,
                embedder=self._embedder_name,
                tokenizer=type(self._tokenizer).__name__,
                compiled=compiled,
                operators=actuals,
            )
        )
        return bundle_id, compiled.prompt, compiled.admitted

    async def attach(
        self, *, org_id: OrgId, message_id: ChatMessageId, bundle_id: ContextBundleId
    ) -> None:
        await self._repository.attach(
            AttachBundleCommand(org_id=org_id, message_id=message_id, bundle_id=bundle_id)
        )

    async def get_for_message(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId
    ) -> ContextBundleSummary | None:
        return await self._repository.get_for_message(
            org_id=org_id,
            user_id=user_id,
            message_id=message_id,
        )
