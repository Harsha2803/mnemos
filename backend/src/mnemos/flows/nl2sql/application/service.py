"""The NL2SQL flow: generate SQL behind the AST guard, execute it as
`mnemos_ro`, narrate the result, persist the assistant turn.

Mirrors `flows/rag/application/service.py`'s `RagFlow` shape: `features/chat`
(persistence, the streaming shape) and `features/datasources` (generation,
the guard, execution) meet here because `features` must never import `flows`
(ADAPTATION §5) — `RagFlow` and `Nl2SqlFlow` are the two places allowed to
know about both sides.

**The security invariant this module exists to hold** (TRACKER §5
deliverable 4):

```
generated SQL -> guard_sql() -> REJECTED_* -> NEVER EXECUTE
                              -> ALLOWED    -> execution
```

Every attempt — the first and every repair — is independently guarded by
`SqlGenerationService.generate()` before this module ever calls
`DatasourceService.execute()`. This module never re-guards, never modifies a
guarded string, and calls `.execute()` exactly once, only when the *final*
attempt's own verdict is `ALLOWED`.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

from mnemos.core.errors import NotFoundError, UpstreamError
from mnemos.core.logging import get_logger
from mnemos.core.types import MessageRole, SqlVerdict
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.domain import (
    AssistantDone,
    AssistantError,
    AssistantToken,
    ChatSessionId,
    ChatStreamEvent,
)
from mnemos.features.datasources.application.generation import (
    RepairContext,
    SqlGenerationService,
)
from mnemos.features.datasources.application.ports import (
    ExecutionOutcome,
    SqlRunRecord,
    SqlRunRepository,
)
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.llm.domain.model import ChatDone, ChatModel, ChatToken, ChatTurn
from mnemos.flows.nl2sql.domain import (
    NARRATION_SYSTEM_PROMPT,
    build_result_block,
    denial_narration,
    execution_error_narration,
)

log = get_logger(__name__)

FLOW_NAME = "nl2sql"

#: What `model` is recorded as on the assistant message when the answer was
#: templated rather than generated — a denial or an execution failure never
#: calls `ChatModel`, and recording the real model name there would claim a
#: completion that did not happen.
_NO_MODEL_CALL = "none"

#: Every rejection kind is eligible for repair (TRACKER §5: "a repaired query
#: *after a rejection*"). A repair attempt is independently guarded by
#: `guard_sql` the same as attempt 1 — retrying after a deliberate write
#: attempt is not a security weakening, only another chance for the model to
#: produce a read, and it still executes only if that chance produces
#: `ALLOWED`.
_REPAIRABLE = frozenset(SqlVerdict) - {SqlVerdict.ALLOWED}


class Nl2SqlFlow:
    def __init__(
        self,
        *,
        chat_repository: ChatRepository,
        datasources: DatasourceService,
        generation: SqlGenerationService,
        sql_runs: SqlRunRepository,
        model: ChatModel,
        datasource_slug: str,
        statement_timeout_ms: int,
        max_rows: int,
        repair_attempts: int,
    ) -> None:
        self._chat = chat_repository
        self._datasources = datasources
        self._generation = generation
        self._sql_runs = sql_runs
        self._model = model
        self._datasource_slug = datasource_slug
        self._statement_timeout_ms = statement_timeout_ms
        self._max_rows = max_rows
        self._repair_attempts = repair_attempts

    async def stream_reply(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        session_id: ChatSessionId,
        content: str,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        session = await self._chat.get_session(org_id=org_id, session_id=session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError(f"chat session {session_id} not found")

        await self._chat.append_user_message(org_id=org_id, session_id=session_id, content=content)

        record = await self._generate_with_repair(org_id=org_id, question=content)

        if record.verdict != SqlVerdict.ALLOWED:
            narration = denial_narration(
                verdict=record.verdict, detail=record.verdict_detail, sql=record.generated_sql
            )
            yield await self._finish(
                org_id=org_id,
                session_id=session_id,
                record=record,
                narration=narration,
                outcome=None,
                model=_NO_MODEL_CALL,
            )
            return

        outcome = await self._datasources.execute(
            org_id=org_id,
            slug=self._datasource_slug,
            sql=record.generated_sql,
            statement_timeout_ms=self._statement_timeout_ms,
            max_rows=self._max_rows,
        )
        record = await self._sql_runs.record_execution(
            org_id=org_id,
            sql_run_id=record.id,
            executed=outcome.error_code is None,
            row_count=outcome.row_count,
            truncated=outcome.truncated,
            duration_ms=outcome.duration_ms,
            error_code=outcome.error_code,
            error_detail=outcome.error_detail,
        )

        if outcome.error_code is not None:
            yield await self._finish(
                org_id=org_id,
                session_id=session_id,
                record=record,
                narration=execution_error_narration(outcome),
                outcome=outcome,
                model=_NO_MODEL_CALL,
            )
            return

        turns = [
            ChatTurn(role=MessageRole.SYSTEM, content=NARRATION_SYSTEM_PROMPT),
            ChatTurn(
                role=MessageRole.SYSTEM,
                content=f"SQL that was run:\n```sql\n{record.generated_sql}\n```",
            ),
            ChatTurn(role=MessageRole.SYSTEM, content=build_result_block(outcome)),
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
                    yield await self._finish(
                        org_id=org_id,
                        session_id=session_id,
                        record=record,
                        narration="".join(pieces),
                        outcome=outcome,
                        model=self._model.model_name,
                        prompt_tokens=event.prompt_tokens,
                        completion_tokens=event.completion_tokens,
                        finish_reason=event.finish_reason,
                        latency_ms=int((time.perf_counter() - start) * 1000),
                    )
                    return
        except UpstreamError:
            if not started:
                raise
            log.warning("nl2sql.upstream_error_mid_stream", session_id=str(session_id))
            yield AssistantError(message="the model is unavailable right now")
            return

    async def _generate_with_repair(self, *, org_id: OrgId, question: str) -> SqlRunRecord:
        """Attempt 1, then up to `self._repair_attempts` more — each one
        independently guarded, each one its own `sql_run` row. Stops the
        moment a verdict is `ALLOWED`, or once the bound is spent, whichever
        comes first; the bound is a hard stop, never an unbounded retry
        (CodingStandards §3, "every external call has an explicit timeout" —
        the same discipline applied to attempt count).
        """
        record = await self._generation.generate(
            org_id=org_id, slug=self._datasource_slug, question=question
        )
        attempt = 1
        while record.verdict in _REPAIRABLE and attempt <= self._repair_attempts:
            attempt += 1
            record = await self._generation.generate(
                org_id=org_id,
                slug=self._datasource_slug,
                question=question,
                attempt=attempt,
                repair=RepairContext(
                    previous_sql=record.generated_sql, detail=record.verdict_detail
                ),
            )
        return record

    async def _finish(
        self,
        *,
        org_id: OrgId,
        session_id: ChatSessionId,
        record: SqlRunRecord,
        narration: str,
        outcome: ExecutionOutcome | None,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        finish_reason: str = "stop",
        latency_ms: int = 0,
    ) -> AssistantDone:
        """Persist the assistant turn, link the `sql_run` row to it, and
        build the `AssistantDone.extra` payload the SSE `done` frame carries
        — the single coherent NL2SQL result the frontend reads, rather than
        a second request reconstructing it from a `sql_run` id.
        """
        message = await self._chat.append_assistant_message(
            org_id=org_id,
            session_id=session_id,
            content=narration,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            model=model,
            finish_reason=finish_reason,
            flow=FLOW_NAME,
        )
        await self._sql_runs.attach_to_message(
            org_id=org_id, sql_run_id=record.id, message_id=message.id
        )
        # `Any`: a heterogeneous JSON bag assembled from several already-typed
        # sources (`str`, `int | None`, `bool`, `list[str]`, nested rows) —
        # the same justification `chat_message.msg_metadata`'s own `dict[str,
        # Any]` carries. `AssistantDone.extra`'s declared type (`dict[str,
        # JsonValue] | None`) is still the contract a reader outside this
        # method sees; `Any` here is only how the literal gets built without
        # fighting `list[JsonValue]`'s invariance over each already-concrete
        # element type.
        extra: dict[str, Any] = {
            "sql": record.generated_sql,
            "verdict": record.verdict.value,
            "verdict_detail": record.verdict_detail,
            "attempt": record.attempt,
            "authorized_tables": list(record.authorized_tables),
            "denied_tables": list(record.denied_tables),
            "executed": record.executed,
            "row_count": outcome.row_count if outcome is not None else None,
            "truncated": outcome.truncated if outcome is not None else False,
            "duration_ms": outcome.duration_ms if outcome is not None else record.duration_ms,
            "error_code": outcome.error_code if outcome is not None else None,
            "error_detail": outcome.error_detail if outcome is not None else None,
            "columns": list(outcome.columns) if outcome is not None else [],
            "rows": [list(row) for row in outcome.rows] if outcome is not None else [],
        }
        return AssistantDone(message=message, extra=extra)
