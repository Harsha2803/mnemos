"""The AST read-only guard — the first of `A3`'s two independent defences
(TRACKER §5 deliverable 3; ADAPTATION §9 "two independent defences, neither
sufficient alone"). The second is `mnemos_ro`, a Postgres role that cannot
write regardless of what this guard decides.

Deliberately an **allowlist**, not a blocklist. The guard requires the parsed
statement to be `sqlglot.exp.Query` (a `SELECT`, optionally `WITH`-prefixed,
or a set operation over `SELECT`s) and then walks *every* node in the tree —
not just the top level — for anything that writes, changes privileges, or is
a shape `sqlglot` could not specifically classify. A blocklist has to name
every dangerous thing in advance; testing one here found that
`SELECT ... INTO`, `FOR UPDATE`, `COPY`, and `EXPLAIN`/`VACUUM`/`CALL` (which
`sqlglot` falls back to parsing as a generic `Command`) all slip past a
blocklist scoped to `INSERT`/`UPDATE`/`DELETE`/`DDL`, because none of them
*is* one of those node types — they are simply not a `Query`. Requiring the
positive case closes that gap by construction instead of by enumeration.

Walking the whole tree, not just the top-level node, is what makes "rejected
wherever it appears" true: a `DELETE ... RETURNING *` is valid Postgres syntax
inside a `WITH` clause, and that data-modifying CTE can then be consumed by a
top-level `SELECT`, referenced from inside a `UNION` arm, or wrapped in a
`FROM (...)` subquery — three different nesting shapes that all present the
same way at the top level (`Select`) and only differ in what `.walk()` finds
underneath. A guard that checks only the root node's type passes a naive test
and fails all three of those.

What this guard does **not** do, deliberately: it does not evaluate function
calls. `SELECT pg_terminate_backend(123)` parses as an ordinary read and is
structurally indistinguishable from a harmless one — there is no AST shape
that separates "safe function" from "dangerous function", only a name, and a
function-name blocklist is unbounded and exactly the kind of enumeration this
module exists to avoid. That gap is real and is closed by the *second*
defence instead: `mnemos_ro` has no `EXECUTE` privilege on administrative
functions and no write privilege at all, so this guard does not need to
pretend it closes a gap the database already closes structurally.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from mnemos.core.types import SqlVerdict

#: Reachable anywhere in the tree, at any depth, this means "not a read" —
#: `.walk()` does not care whether the node is the root or nested three CTEs
#: deep, which is the entire point (see module docstring).
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
    exp.Into,  # `SELECT ... INTO new_table` — a read that creates a table
    exp.Lock,  # `FOR UPDATE` / `FOR SHARE` — a locking read, not a plain one
    exp.Command,  # sqlglot's fallback for syntax it does not specifically
    # model (EXPLAIN, VACUUM, CALL, ...). Unrecognised is untrusted, not
    # passed through — the same fail-closed reasoning as an unparseable
    # statement, just discovered one layer later.
)


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    """What the guard decided about one candidate statement.

    `authorized_tables` and `denied_tables` are mutually exclusive by
    construction — every table the statement touches lands in the first list
    on `ALLOWED` and the second on any rejection — because that split is
    exactly what `sql_run.authorized_tables`/`.denied_tables` records for the
    audit trail (`adapters/models.py`'s `SqlRun` docstring) and what
    deliverable 5's denial screen names on the wire.
    """

    verdict: SqlVerdict
    detail: str | None
    authorized_tables: list[str] = field(default_factory=list)
    denied_tables: list[str] = field(default_factory=list)


def guard_sql(sql: str) -> GuardVerdict:
    """Decide whether `sql` is a single Postgres read.

    Fail-closed at every branch: an empty statement, a parse failure, or
    anything that parses but is not affirmatively a read is rejected — never
    passed through on the theory that `mnemos_ro` will catch it. That role is
    real and is proven independently
    (`test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed`), but
    it is the second defence, not a reason for this one to be careless.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return GuardVerdict(verdict=SqlVerdict.REJECTED_UNPARSEABLE, detail="empty statement")

    try:
        tree = sqlglot.parse_one(stripped, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except SqlglotError as exc:
        detail = str(exc).splitlines()[0]
        return GuardVerdict(verdict=SqlVerdict.REJECTED_UNPARSEABLE, detail=detail)

    if not isinstance(tree, exp.Query):
        detail = (
            "multiple statements in one request — Mnemos executes exactly one"
            if isinstance(tree, exp.Block)
            else f"not a read statement (parsed as {type(tree).__name__})"
        )
        return GuardVerdict(
            verdict=SqlVerdict.REJECTED_WRITE, detail=detail, denied_tables=_touched_tables(tree)
        )

    offender = next((node for node in tree.walk() if isinstance(node, _FORBIDDEN_NODES)), None)
    if offender is not None:
        return GuardVerdict(
            verdict=SqlVerdict.REJECTED_WRITE,
            detail=f"contains {type(offender).__name__} — Mnemos only reads",
            denied_tables=_touched_tables(tree),
        )

    return GuardVerdict(
        verdict=SqlVerdict.ALLOWED, detail=None, authorized_tables=_touched_tables(tree)
    )


def _touched_tables(tree: exp.Expr) -> list[str]:
    """Every table the statement names, schema-qualified where the SQL
    qualified it, in first-seen order. CTE aliases are excluded: a reference
    to `WITH recent AS (...) SELECT * FROM recent` names the CTE, not a
    table, and listing it as one would misrepresent what was actually read.
    """
    cte_aliases = {cte.alias for cte in tree.find_all(exp.CTE)}
    names: list[str] = []
    seen: set[str] = set()
    for table in tree.find_all(exp.Table):
        if not table.db and table.name in cte_aliases:
            continue
        qualified = f"{table.db}.{table.name}" if table.db else table.name
        if qualified not in seen:
            seen.add(qualified)
            names.append(qualified)
    return names
