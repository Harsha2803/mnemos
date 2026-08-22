"""`SqlGenerationService`: turn a question into guarded, recorded SQL.

Deliberately a sibling of `DatasourceService`, not a fifth method on it and
not a new `flows/nl2sql/` package. `DatasourceService` is about the
datasource *resource* — register it, cache its schema, seed its glossary,
render what is cached — and every one of those is fast and has no security
verdict to make. Generation calls a model and decides whether the result is
safe to ever execute, which is a different kind of operation with different
tests and different fakes; composing `DatasourceService` (for
`require_datasource` and `render_context`) rather than growing it mirrors how
`flows/rag/application/service.py`'s `RagFlow` composes `KnowledgeService`
rather than adding a `stream_reply` method to it.

Not `flows/nl2sql/`, though the shape rhymes with `RagFlow`: TRACKER §5 was
explicit that deliverables 3-4 are "more of this feature, not a new one" —
deliverable 4's repair loop (below) is still reasoned about entirely inside
`features/datasources`, one call to `generate()` per attempt; `flows/
nl2sql/` is where the loop itself lives, because *stopping* the loop and
deciding what to execute is a fact about the chat turn, not about
generation. `generate()` here is one blocking call — `ChatModel.complete`,
not `.stream` — because nothing can be guarded, let alone shown, before the
whole statement has arrived; the port docstring already anticipates exactly
this kind of non-streaming caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from mnemos.core.logging import get_logger
from mnemos.core.types import MessageRole, SqlVerdict
from mnemos.features.datasources.application.ports import SqlRunRecord, SqlRunRepository
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.datasources.domain import (
    NL2SQL_SYSTEM_PROMPT,
    build_repair_prompt,
    extract_sql_statement,
    guard_sql,
)
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.llm.domain.model import ChatModel, ChatTurn
from mnemos.features.observability.application.ports import AuditRepository

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RepairContext:
    """What a repair attempt (attempt 2, 3, ...) adds to the prompt: the
    statement the guard just rejected and why. `Nl2SqlFlow` builds one from
    the previous attempt's own `SqlRunRecord` — never from anything the
    guard has not already verdicted, so a repair prompt can never quote SQL
    this service has not itself seen and recorded.
    """

    previous_sql: str
    detail: str | None


class SqlGenerationService:
    def __init__(
        self,
        *,
        datasources: DatasourceService,
        model: ChatModel,
        sql_runs: SqlRunRepository,
        audit: AuditRepository | None = None,
    ) -> None:
        self._datasources = datasources
        self._model = model
        self._sql_runs = sql_runs
        # Optional so every existing test construction of this service keeps
        # working unchanged (TRACKER §5 deliverable 5).
        self._audit = audit

    async def generate(
        self,
        *,
        org_id: OrgId,
        slug: str,
        question: str,
        attempt: int = 1,
        repair: RepairContext | None = None,
        user_id: UserId | None = None,
    ) -> SqlRunRecord:
        """Generate one candidate statement for `question`, guard it, and
        record the attempt regardless of the verdict.

        `attempt` and `repair` default to a single, one-shot attempt — every
        deliverable-3 call site (the CLI, existing tests) is unaffected.
        `Nl2SqlFlow`'s repair loop (deliverable 4) is the caller that passes
        `attempt=2` and a `RepairContext` built from attempt 1's rejected
        record, and does so as its own new call to `generate()` — this
        method still does not loop internally.

        Raises `LookupError` for an unregistered slug, or one registered to
        a different org — `require_datasource`'s lookup is `org_id`-scoped,
        so another org's datasource is indistinguishable from a nonexistent
        one, which is the property `test_a_query_against_another_orgs_
        datasource_is_a_404` pins.
        """
        datasource = await self._datasources.require_datasource(org_id=org_id, slug=slug)
        schema_context = await self._datasources.render_context(org_id=org_id, slug=slug)

        turns = [
            ChatTurn(role=MessageRole.SYSTEM, content=NL2SQL_SYSTEM_PROMPT),
            ChatTurn(role=MessageRole.SYSTEM, content=schema_context),
            ChatTurn(role=MessageRole.USER, content=question),
        ]
        if repair is not None:
            turns.append(
                ChatTurn(role=MessageRole.ASSISTANT, content=f"```sql\n{repair.previous_sql}\n```")
            )
            turns.append(
                ChatTurn(
                    role=MessageRole.USER,
                    content=build_repair_prompt(
                        previous_sql=repair.previous_sql, detail=repair.detail
                    ),
                )
            )

        completion = await self._model.complete(turns)
        candidate_sql = extract_sql_statement(completion.content)
        verdict = guard_sql(candidate_sql)

        record = await self._sql_runs.record_attempt(
            org_id=org_id,
            datasource_id=datasource.id,
            message_id=None,
            attempt=attempt,
            question=question,
            generated_sql=candidate_sql,
            verdict=verdict.verdict,
            verdict_detail=verdict.detail,
            authorized_tables=verdict.authorized_tables,
            denied_tables=verdict.denied_tables,
        )
        log.info(
            "datasources.sql_generated",
            org_id=str(org_id),
            datasource_slug=slug,
            attempt=attempt,
            verdict=verdict.verdict.value,
        )
        # Only the write rejection is audited here — the exact "watch a user
        # be refused, and see why" moment TRACKER §5 deliverable 5 names.
        # Unauthorized-table, unparseable and too-complex verdicts are real
        # rejections too, but this milestone's audit scope is bounded to the
        # one call site named in the brief, deliberately, not every possible
        # guard outcome.
        if verdict.verdict is SqlVerdict.REJECTED_WRITE and self._audit is not None:
            await self._audit.record(
                org_id=org_id,
                actor_id=user_id,
                actor_kind="user" if user_id is not None else "system",
                action="datasource.query",
                resource_kind="datasource",
                resource_id=str(datasource.id),
                outcome="deny",
                reason=verdict.detail,
            )
        return record
