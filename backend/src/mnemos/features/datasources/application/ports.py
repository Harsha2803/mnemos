"""What `DatasourceService` needs from persistence and the warehouse itself, as
`Protocol`s — the adapters satisfy these structurally, matching
`features/knowledge`'s pattern."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mnemos.core.types import SqlVerdict
from mnemos.features.datasources.domain import (
    DatasourceId,
    GlossaryTermRow,
    IntrospectedColumn,
    IntrospectedTable,
    SchemaObjectDraft,
    SqlRunId,
)
from mnemos.features.identity.domain import OrgId


@dataclass(frozen=True, slots=True)
class DatasourceRecord:
    id: DatasourceId
    org_id: OrgId
    slug: str
    name: str
    dialect: str
    dsn_encrypted: bytes
    read_only_role: str
    allowed_schemas: list[str]
    allowed_tables: list[str]
    introspected_at: datetime | None


class SchemaIntrospector(Protocol):
    async def introspect(
        self, *, dsn: str, schemas: list[str]
    ) -> tuple[list[IntrospectedTable], list[IntrospectedColumn]]: ...


class DatasourceRepository(Protocol):
    async def get_by_slug(self, *, org_id: OrgId, slug: str) -> DatasourceRecord | None: ...

    async def ensure_datasource(
        self,
        *,
        org_id: OrgId,
        slug: str,
        name: str,
        description: str,
        dsn_encrypted: bytes,
        read_only_role: str,
        allowed_schemas: list[str],
    ) -> DatasourceRecord: ...

    async def mark_introspected(self, *, org_id: OrgId, datasource_id: DatasourceId) -> None: ...


class SchemaObjectRepository(Protocol):
    async def replace_all(
        self,
        *,
        org_id: OrgId,
        datasource_id: DatasourceId,
        drafts: list[SchemaObjectDraft],
    ) -> int:
        """Replace the cached schema for one datasource and return the row count.

        A full replace, not a diff: a dropped table must disappear from the
        cache on the next refresh, and refresh is already the explicit,
        infrequent action that makes a delete-then-insert cheap enough.
        """
        ...

    async def list_all(
        self, *, org_id: OrgId, datasource_id: DatasourceId
    ) -> list[SchemaObjectDraft]:
        """The cached schema, table rows before their columns — what
        `render_schema_context` renders. `SchemaObjectDraft` doubles as the
        read shape too; a cached row and a row about to be cached carry
        exactly the same fields."""
        ...


class GlossaryRepository(Protocol):
    async def ensure_terms(
        self, *, org_id: OrgId, datasource_id: DatasourceId, terms: list[GlossaryTermRow]
    ) -> int:
        """Idempotent per term, matched by `term` text: a term already present
        is left untouched, so re-running the seed never overwrites an edit
        made since. Returns how many were newly written."""
        ...

    async def list_terms(
        self, *, org_id: OrgId, datasource_id: DatasourceId
    ) -> list[GlossaryTermRow]: ...


@dataclass(frozen=True, slots=True)
class SqlRunRecord:
    id: SqlRunId
    org_id: OrgId
    datasource_id: DatasourceId
    attempt: int
    question: str
    generated_sql: str
    verdict: SqlVerdict
    verdict_detail: str | None
    authorized_tables: list[str]
    denied_tables: list[str]
    #: Unset until `SqlRunRepository.attach_to_message` runs, after the
    #: assistant message it belongs to is persisted (deliverable 4) — the
    #: same "message must exist first" sequencing `add_citations` already
    #: follows for `flows/rag`.
    message_id: uuid.UUID | None = None
    #: Execution outcome, filled in by `record_execution` for an `ALLOWED`
    #: verdict only. A `REJECTED_*` record keeps every field below at its
    #: default — `executed=False` is the fact the security invariant rests
    #: on, not an unset placeholder.
    executed: bool = False
    row_count: int | None = None
    truncated: bool = False
    duration_ms: int | None = None
    error_code: str | None = None
    error_detail: str | None = None


class SqlRunRepository(Protocol):
    async def record_attempt(
        self,
        *,
        org_id: OrgId,
        datasource_id: DatasourceId,
        message_id: uuid.UUID | None,
        attempt: int,
        question: str,
        generated_sql: str,
        verdict: SqlVerdict,
        verdict_detail: str | None,
        authorized_tables: list[str],
        denied_tables: list[str],
    ) -> SqlRunRecord:
        """Persist one generation attempt and its verdict, successful or not.

        `message_id` is nullable because deliverable 3 has no chat message to
        attach to yet (`flows/nl2sql/`, deliverable 4, is what will pass a
        real one) — every attempt is still recorded, just not yet linked to a
        conversation turn. `attempt` is supplied by the caller rather than
        computed here, so a repair loop (deliverable 4,
        `Settings.sql_repair_attempts`) can record attempt 2, 3, ... against
        the same question without this port changing shape.
        """
        ...

    async def record_execution(
        self,
        *,
        org_id: OrgId,
        sql_run_id: SqlRunId,
        executed: bool,
        row_count: int | None,
        truncated: bool,
        duration_ms: int | None,
        error_code: str | None,
        error_detail: str | None,
    ) -> SqlRunRecord:
        """Fill in the six execution columns `adapters/models.py`'s `SqlRun`
        has carried, unused, since `M2`. Called at most once per attempt,
        only for a run whose verdict was already `ALLOWED` — deliverable 4's
        flow never calls this for a `REJECTED_*` record, which is what makes
        `executed=False` on a rejected row a fact the guard produced rather
        than a value this method happened not to set.
        """
        ...

    async def attach_to_message(
        self, *, org_id: OrgId, sql_run_id: SqlRunId, message_id: uuid.UUID
    ) -> None:
        """Link a recorded attempt to the assistant message it produced.

        Called after `ChatRepository.append_assistant_message` returns, the
        same ordering `add_citations` uses and for the same reason: a message
        id cannot exist before the message does, so persisting the message
        and linking to it are always two sequential calls, never one.
        """
        ...


#: What a SQL cell can hold once every Postgres type the demo schema and a
#: model-generated `SELECT` can plausibly produce (numeric, text, boolean,
#: date/time, `Decimal`, `UUID`, `None`, ...) is normalised to something a
#: JSON response and a `ChatTurn` narrating over it can both hold without
#: either needing to know the original column type.
SqlCellValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """What running one `ALLOWED` statement as `mnemos_ro` produced.

    `error_code`/`error_detail` are set only when Postgres itself rejected
    the statement at execution time (a semantic error the guard has no way
    to see, e.g. a column name the model invented) — the guard already
    proved this is not a *write*, so a runtime failure here is always about
    correctness, never about safety.
    """

    columns: list[str]
    rows: list[list[SqlCellValue]]
    row_count: int
    truncated: bool
    duration_ms: int
    error_code: str | None = None
    error_detail: str | None = None


class SqlExecutor(Protocol):
    async def execute(
        self, *, dsn: str, sql: str, statement_timeout_ms: int, max_rows: int
    ) -> ExecutionOutcome:
        """Run exactly the statement it is given, once, against `dsn`.

        `sql` must already be an `ALLOWED` `guard_sql` verdict — this port
        does not guard, does not parse, and does not modify what it is
        handed (no `LIMIT` appended by string-building): capping rows is the
        caller fetching at most `max_rows + 1` from the cursor, not rewriting
        the statement guarded upstream. A statement that runs past
        `statement_timeout_ms` is cancelled by Postgres itself and surfaces
        as an `ExecutionOutcome` with `error_code="statement_timeout"`, never
        as a hung connection.
        """
        ...
