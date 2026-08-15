"""`SqlExecutor` over Postgres: run one already-`ALLOWED` statement as
`mnemos_ro`, capped and timed out.

Mirrors `introspection.py`'s short-lived-engine pattern — a `create_async_
engine(dsn, pool_size=1, ...)` per call, disposed after, because execution is
one request-scoped query against `mnemos_analytics`, never a connection the
flow holds open. `statement_timeout` is set as an asyncpg connection
parameter (`server_settings`), not a `SET` statement built with the guarded
SQL string — the guarded statement is executed exactly as guarded, with
nothing built around it (TRACKER §5 deliverable 4, "never interpolate the
model's SQL into another statement").
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from datetime import time as time_
from decimal import Decimal
from uuid import UUID

import asyncpg
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from mnemos.features.datasources.application.ports import ExecutionOutcome, SqlCellValue

#: A backstop above the Postgres-side `statement_timeout`, in case a hung TCP
#: connection (not a running query Postgres can cancel) is what is actually
#: stuck — CodingStandards §3, every external call has an explicit timeout.
_ASYNC_TIMEOUT_SLACK_S = 2.0


def _is_query_canceled(exc: DBAPIError) -> bool:
    """`statement_timeout` firing is `asyncpg.exceptions.QueryCanceledError`,
    but SQLAlchemy's asyncpg dialect wraps every driver error in its own
    `AsyncAdapt_asyncpg_dbapi.Error` before it reaches `DBAPIError.orig` — the
    real asyncpg exception is that wrapper's `__cause__`, not `.orig` itself.
    Checked defensively (`getattr` + `or`) rather than assumed, since that
    wrapping is a SQLAlchemy implementation detail this module does not own.
    """
    candidates = (exc.orig, getattr(exc.orig, "__cause__", None))
    return any(isinstance(c, asyncpg.exceptions.QueryCanceledError) for c in candidates)


def _to_cell(value: object) -> SqlCellValue:
    """Normalise one result cell to a JSON-safe scalar.

    A model-generated `SELECT` can return any Postgres type the demo schema
    has — `Decimal` (numeric columns), `date`/`datetime`/`time` (order
    dates), `UUID` (primary keys). None of those survive a JSON response or
    a `ChatTurn` narrating over them as-is, and the narration prompt needs a
    string it can read regardless.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time_, timedelta, UUID)):
        return str(value)
    return str(value)


class PostgresExecutor:
    async def execute(
        self, *, dsn: str, sql: str, statement_timeout_ms: int, max_rows: int
    ) -> ExecutionOutcome:
        engine = create_async_engine(
            dsn,
            pool_size=1,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={"server_settings": {"statement_timeout": str(statement_timeout_ms)}},
        )
        start = time.perf_counter()
        try:
            async with asyncio.timeout(statement_timeout_ms / 1000 + _ASYNC_TIMEOUT_SLACK_S):
                async with engine.connect() as conn:
                    result = await conn.execute(text(sql))
                    columns = list(result.keys())
                    fetched = result.fetchmany(max_rows + 1)
                    truncated = len(fetched) > max_rows
                    rows = [list(row) for row in fetched[:max_rows]]
        except TimeoutError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return ExecutionOutcome(
                columns=[],
                rows=[],
                row_count=0,
                truncated=False,
                duration_ms=duration_ms,
                error_code="statement_timeout",
                error_detail=f"exceeded the {statement_timeout_ms}ms statement timeout",
            )
        except DBAPIError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if _is_query_canceled(exc):
                return ExecutionOutcome(
                    columns=[],
                    rows=[],
                    row_count=0,
                    truncated=False,
                    duration_ms=duration_ms,
                    error_code="statement_timeout",
                    error_detail=f"exceeded the {statement_timeout_ms}ms statement timeout",
                )
            detail = str(exc.orig if exc.orig is not None else exc).splitlines()[0]
            return ExecutionOutcome(
                columns=[],
                rows=[],
                row_count=0,
                truncated=False,
                duration_ms=duration_ms,
                error_code="execution_error",
                error_detail=detail,
            )
        finally:
            await engine.dispose()

        duration_ms = int((time.perf_counter() - start) * 1000)
        normalised_rows: list[list[SqlCellValue]] = [[_to_cell(v) for v in row] for row in rows]
        return ExecutionOutcome(
            columns=columns,
            rows=normalised_rows,
            row_count=len(normalised_rows),
            truncated=truncated,
            duration_ms=duration_ms,
        )
