"""`A3` deliverable 3 — the AST read-only guard, CodingStandards §9 mandatory
case 4: "DML nested inside a CTE, inside a UNION, and inside a subquery is
rejected; unparseable SQL is rejected fail-closed rather than passed
through."

Pure and synchronous throughout — no Postgres, no `ChatModel`, no
`pytest.mark.asyncio` — because `guard_sql` is a pure function of a string.
`test_datasources_generation.py` covers the guard wired into
`SqlGenerationService` against a real model and a real Postgres, including
`test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed`, the proof
that the *second* defence holds even when this one is bypassed entirely.
"""

from __future__ import annotations

import pytest

from mnemos.core.types import SqlVerdict
from mnemos.features.datasources.domain import guard_sql


def test_a_select_is_allowed() -> None:
    """The control: a guard that rejects everything passes every rejection
    test below for free. This is the one that proves it does not."""
    result = guard_sql("SELECT customer_id, name FROM analytics.customer")
    assert result.verdict == SqlVerdict.ALLOWED
    assert result.authorized_tables == ["analytics.customer"]
    assert result.denied_tables == []


def test_a_read_query_with_a_read_only_cte_and_a_join_is_allowed() -> None:
    """A realistic multi-table analytic query — CTE, joins, date arithmetic,
    aggregation — the shape a real question would actually generate. The
    guard must not be so strict that it rejects ordinary read SQL."""
    result = guard_sql(
        """
        WITH recent AS (
            SELECT so.customer_id, so.net_amount
            FROM analytics.sales_order so
            WHERE so.status = 'completed' AND so.ordered_on >= CURRENT_DATE - INTERVAL '90 days'
        )
        SELECT c.segment, SUM(recent.net_amount) AS revenue
        FROM recent
        JOIN analytics.customer c ON c.customer_id = recent.customer_id
        GROUP BY c.segment
        ORDER BY revenue DESC
        """
    )
    assert result.verdict == SqlVerdict.ALLOWED
    assert set(result.authorized_tables) == {"analytics.sales_order", "analytics.customer"}
    # The CTE's own name must never be reported as a table touched.
    assert "recent" not in result.authorized_tables


def test_a_union_of_reads_is_allowed() -> None:
    result = guard_sql(
        "SELECT customer_name FROM analytics.customer "
        "UNION SELECT product_name FROM analytics.product"
    )
    assert result.verdict == SqlVerdict.ALLOWED


def test_a_trailing_semicolon_does_not_confuse_the_guard() -> None:
    assert guard_sql("SELECT * FROM analytics.region;").verdict == SqlVerdict.ALLOWED


@pytest.mark.parametrize(
    ("label", "sql"),
    [
        (
            "inside_a_cte",
            "WITH d AS (DELETE FROM analytics.region RETURNING *) SELECT * FROM d",
        ),
        (
            "inside_a_union_arm",
            "(WITH d AS (DELETE FROM analytics.region RETURNING *) SELECT * FROM d) "
            "UNION SELECT * FROM analytics.customer",
        ),
        (
            "inside_a_subquery",
            "SELECT * FROM (WITH d AS (DELETE FROM analytics.region RETURNING *) "
            "SELECT * FROM d) sub",
        ),
    ],
)
def test_dml_is_rejected_inside_a_cte_a_union_and_a_subquery(label: str, sql: str) -> None:
    """The whole point of walking the tree instead of checking the top-level
    node type: all three of these parse to a top-level `Select` — a guard
    that only inspects the root passes a naive "is it a SELECT" test and lets
    every one of these through. `DELETE ... RETURNING *` inside a `WITH`
    clause is valid Postgres syntax, and Postgres allows a data-modifying CTE
    to be consumed from a top-level query, a UNION arm, or a subquery alike.
    """
    result = guard_sql(sql)
    assert result.verdict == SqlVerdict.REJECTED_WRITE, label
    assert "analytics.region" in result.denied_tables, label
    assert result.authorized_tables == [], label


@pytest.mark.parametrize(
    "sql",
    [
        "not even sql at all $$ ((",
        "",
        "   ",
        "SELECT * FROM analytics.customer WHERE id IN (UPDATE analytics.region SET name='x')",
    ],
)
def test_unparseable_sql_is_rejected_fail_closed(sql: str) -> None:
    result = guard_sql(sql)
    assert result.verdict == SqlVerdict.REJECTED_UNPARSEABLE
    assert result.detail is not None
    assert result.authorized_tables == []
    assert result.denied_tables == []


@pytest.mark.parametrize(
    ("label", "sql"),
    [
        ("insert", "INSERT INTO analytics.region (region_name) VALUES ('nowhere')"),
        ("update", "UPDATE analytics.region SET region_name = 'x'"),
        ("delete", "DELETE FROM analytics.region"),
        (
            "merge",
            "MERGE INTO analytics.region t USING analytics.customer c ON t.region_id = "
            "c.region_id WHEN MATCHED THEN UPDATE SET t.region_name = c.customer_name",
        ),
        ("truncate", "TRUNCATE TABLE analytics.region"),
        ("drop", "DROP TABLE analytics.region"),
        ("alter", "ALTER TABLE analytics.region ADD COLUMN evil int"),
        ("create", "CREATE TABLE evil (id int)"),
        ("grant", "GRANT SELECT ON analytics.region TO someone"),
        ("select_into_creates_a_table", "SELECT * INTO new_table FROM analytics.region"),
        ("for_update_takes_a_write_lock", "SELECT * FROM analytics.region FOR UPDATE"),
        (
            "insert_hidden_in_a_cte",
            "WITH i AS (INSERT INTO analytics.region (region_name) "
            "VALUES ('x') RETURNING *) SELECT * FROM i",
        ),
    ],
)
def test_every_write_and_privilege_shape_is_rejected(label: str, sql: str) -> None:
    result = guard_sql(sql)
    assert result.verdict == SqlVerdict.REJECTED_WRITE, label
    assert result.authorized_tables == [], label


@pytest.mark.parametrize(
    ("label", "sql"),
    [
        # Syntax sqlglot cannot specifically model falls back to a generic
        # `Command` node rather than raising — fail-closed has to catch this
        # one layer later than a parse error, not skip it.
        ("explain", "EXPLAIN SELECT * FROM analytics.region"),
        ("vacuum", "VACUUM analytics.region"),
        ("call_a_procedure", "CALL some_procedure()"),
        # Not a DML/DDL node at all, and not a `Query` either — a blocklist
        # scoped to INSERT/UPDATE/DELETE/DDL would miss these entirely.
        ("copy_to_a_file", "COPY analytics.region TO '/tmp/exfiltrated.csv'"),
        ("set_a_session_variable", "SET search_path TO analytics"),
    ],
)
def test_statement_shapes_a_dml_blocklist_would_miss_are_still_rejected(
    label: str, sql: str
) -> None:
    """These are the reason the guard is an allowlist ("must parse to a
    `Query`") rather than a blocklist of dangerous node types: none of them
    is `INSERT`/`UPDATE`/`DELETE`/`DDL`-shaped, so a guard that only checks
    for those specific node types would let every one of these through."""
    result = guard_sql(sql)
    assert result.verdict == SqlVerdict.REJECTED_WRITE, label


def test_multiple_statements_are_rejected_even_when_every_one_is_a_read() -> None:
    """`sql_run` and the deliverable-3 brief both say "a single read" — two
    harmless `SELECT`s stacked with a semicolon are still not *one*
    statement, and Postgres's simple-query protocol runs every statement in
    a semicolon-separated batch. Rejecting this is also what makes stacked
    DML impossible to sneak past by hiding it after a decoy first statement.
    """
    result = guard_sql("SELECT * FROM analytics.customer; SELECT * FROM analytics.region")
    assert result.verdict == SqlVerdict.REJECTED_WRITE
    assert "multiple statements" in (result.detail or "")


def test_a_decoy_read_does_not_smuggle_a_write_past_the_guard() -> None:
    """The direct attack `test_multiple_statements_are_rejected...` defends
    against: a harmless-looking first statement, a write hidden after it."""
    result = guard_sql("SELECT 1; DROP TABLE analytics.region;")
    assert result.verdict == SqlVerdict.REJECTED_WRITE
    assert "analytics.region" in result.denied_tables


def test_an_unqualified_table_name_is_still_recorded() -> None:
    """No schema prefix (relying on the connection's `search_path`) is valid
    SQL and must still show up in the audit trail, unqualified."""
    result = guard_sql("SELECT * FROM customer")
    assert result.verdict == SqlVerdict.ALLOWED
    assert result.authorized_tables == ["customer"]
