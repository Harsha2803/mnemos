"""`A3` deliverable 4 — `PostgresExecutor`, against a real `mnemos_analytics`
as the real `mnemos_ro` role.

Same argument `test_datasources_generation.py`'s own docstring makes: the
claims here (a real read succeeds, the row cap is enforced by fetching one
past it rather than by rewriting the statement, a statement that outruns its
timeout is cancelled rather than left running) are all claims about Postgres
itself, and a fake connection would only prove the fake behaves.
"""

from __future__ import annotations

import time

import pytest

from mnemos.features.datasources.adapters.executor import PostgresExecutor

from .conftest import Postgres


@pytest.fixture
def executor() -> PostgresExecutor:
    return PostgresExecutor()


@pytest.mark.asyncio
async def test_execute_runs_a_real_read_against_mnemos_analytics(
    executor: PostgresExecutor, postgres: Postgres
) -> None:
    outcome = await executor.execute(
        dsn=postgres.analytics_ro_url,
        sql="SELECT region_name FROM analytics.region ORDER BY region_name",
        statement_timeout_ms=15_000,
        max_rows=5_000,
    )
    assert outcome.error_code is None
    assert outcome.columns == ["region_name"]
    assert outcome.row_count > 0
    assert not outcome.truncated
    assert all(isinstance(row[0], str) for row in outcome.rows)


@pytest.mark.asyncio
async def test_the_result_set_is_capped_at_sql_max_rows(
    executor: PostgresExecutor, postgres: Postgres
) -> None:
    """A synthetic 10-row result, capped to 3 — independent of how large the
    seeded `analytics.*` tables happen to be."""
    outcome = await executor.execute(
        dsn=postgres.analytics_ro_url,
        sql="SELECT g FROM generate_series(1, 10) AS g",
        statement_timeout_ms=15_000,
        max_rows=3,
    )
    assert outcome.error_code is None
    assert outcome.row_count == 3
    assert outcome.truncated is True
    assert [row[0] for row in outcome.rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_result_at_exactly_max_rows_is_not_marked_truncated(
    executor: PostgresExecutor, postgres: Postgres
) -> None:
    outcome = await executor.execute(
        dsn=postgres.analytics_ro_url,
        sql="SELECT g FROM generate_series(1, 3) AS g",
        statement_timeout_ms=15_000,
        max_rows=3,
    )
    assert outcome.row_count == 3
    assert outcome.truncated is False


@pytest.mark.asyncio
async def test_a_statement_that_exceeds_the_timeout_is_cancelled_not_left_running(
    executor: PostgresExecutor, postgres: Postgres
) -> None:
    """`pg_sleep(2)` against a 200ms statement timeout must come back in well
    under 2 seconds, cancelled by Postgres — not merely reported as an error
    after the full sleep ran to completion, which would mean the timeout was
    never actually enforced against the running query."""
    start = time.perf_counter()
    outcome = await executor.execute(
        dsn=postgres.analytics_ro_url,
        sql="SELECT pg_sleep(2)",
        statement_timeout_ms=200,
        max_rows=10,
    )
    elapsed_s = time.perf_counter() - start

    assert outcome.error_code == "statement_timeout"
    assert outcome.row_count == 0
    assert elapsed_s < 1.5, "the query ran past its statement_timeout instead of being cancelled"


@pytest.mark.asyncio
async def test_a_syntactically_invalid_statement_is_reported_not_raised(
    executor: PostgresExecutor, postgres: Postgres
) -> None:
    """A guard-`ALLOWED` statement can still fail *at* the database — an
    invented column is valid SQL syntax the guard cannot see is wrong.
    `execute` must report that as an `ExecutionOutcome`, not let a DBAPI
    exception escape to the caller."""
    outcome = await executor.execute(
        dsn=postgres.analytics_ro_url,
        sql="SELECT no_such_column FROM analytics.region",
        statement_timeout_ms=15_000,
        max_rows=10,
    )
    assert outcome.error_code == "execution_error"
    assert outcome.error_detail is not None
    assert outcome.row_count == 0


@pytest.mark.asyncio
async def test_normalises_non_json_native_cells_to_json_safe_scalars(
    executor: PostgresExecutor, postgres: Postgres
) -> None:
    """`net_amount` is `numeric` (`Decimal`), `ordered_on` is a date — neither
    survives a JSON response or a narration prompt as-is."""
    outcome = await executor.execute(
        dsn=postgres.analytics_ro_url,
        sql="SELECT net_amount, ordered_on FROM analytics.sales_order LIMIT 1",
        statement_timeout_ms=15_000,
        max_rows=10,
    )
    assert outcome.error_code is None
    assert outcome.row_count == 1
    amount, ordered_on = outcome.rows[0]
    assert isinstance(amount, float)
    assert isinstance(ordered_on, str)
