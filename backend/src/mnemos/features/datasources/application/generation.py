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

Not `flows/nl2sql/`, though the shape rhymes with `RagFlow`: TRACKER §5 is
explicit that deliverables 3-4 are "more of this feature, not a new one",
and `flows/` is reserved for deliverable 4, where streaming and the chat
integration actually require it. `generate()` here is one blocking call —
`ChatModel.complete`, not `.stream` — because nothing can be guarded, let
alone shown, before the whole statement has arrived; the port docstring
already anticipates exactly this kind of non-streaming caller.
"""

from __future__ import annotations

from mnemos.core.logging import get_logger
from mnemos.core.types import MessageRole
from mnemos.features.datasources.application.ports import SqlRunRecord, SqlRunRepository
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.datasources.domain import (
    NL2SQL_SYSTEM_PROMPT,
    extract_sql_statement,
    guard_sql,
)
from mnemos.features.identity.domain import OrgId
from mnemos.features.llm.domain.model import ChatModel, ChatTurn

log = get_logger(__name__)

#: No repair loop yet (`Settings.sql_repair_attempts` is deliverable 4's) —
#: every deliverable-3 call is a single, one-shot attempt at the question.
_FIRST_ATTEMPT = 1


class SqlGenerationService:
    def __init__(
        self, *, datasources: DatasourceService, model: ChatModel, sql_runs: SqlRunRepository
    ) -> None:
        self._datasources = datasources
        self._model = model
        self._sql_runs = sql_runs

    async def generate(self, *, org_id: OrgId, slug: str, question: str) -> SqlRunRecord:
        """Generate one candidate statement for `question`, guard it, and
        record the attempt regardless of the verdict.

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
        completion = await self._model.complete(turns)
        candidate_sql = extract_sql_statement(completion.content)
        verdict = guard_sql(candidate_sql)

        record = await self._sql_runs.record_attempt(
            org_id=org_id,
            datasource_id=datasource.id,
            message_id=None,
            attempt=_FIRST_ATTEMPT,
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
            verdict=verdict.verdict.value,
        )
        return record
