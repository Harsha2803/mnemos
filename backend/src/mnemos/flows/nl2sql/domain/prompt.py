"""Pure functions: turning an execution outcome into a narration prompt, and a
rejected/failed attempt into the text a user sees without ever calling the
model over it. No I/O — the same layering `flows/rag/domain/prompt.py` uses,
here inside a flow because a flow is where SQL execution (`features/
datasources`) and conversation (`features/chat`) meet.
"""

from __future__ import annotations

from mnemos.core.types import SqlVerdict
from mnemos.features.datasources.application.ports import ExecutionOutcome

NARRATION_SYSTEM_PROMPT = (
    "You are Mnemos, an enterprise AI assistant answering a question about the "
    "organisation's data warehouse. Below is the exact SQL statement that was run "
    "and the rows it returned. Answer the user's question using only that result "
    "set — never invent a row, a count, or a conclusion the data does not support. "
    "If the result set is empty, say so plainly. If it was truncated, mention that "
    "more rows exist than are shown."
)

#: Cap on how many result rows the narration prompt itself carries. The
#: executor already caps the *response* at `sql_max_rows` — this is a second,
#: much smaller cap so a 5000-row allowed result does not become a 5000-row
#: prompt. `row_count`/`truncated` are stated in the block regardless, so the
#: model always knows the true scope even when it is only shown a sample.
_NARRATION_ROW_SAMPLE = 50


def build_result_block(outcome: ExecutionOutcome) -> str:
    """Render the executed statement's result set as the text the narration
    model reads — a markdown table, so a small local model can read it
    without any special tool-calling support."""
    if outcome.row_count == 0:
        return "The query returned 0 rows."

    sample = outcome.rows[:_NARRATION_ROW_SAMPLE]
    header = " | ".join(outcome.columns)
    separator = " | ".join("---" for _ in outcome.columns)
    body = "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in sample)
    table = f"{header}\n{separator}\n{body}"

    notes = [f"{outcome.row_count} row(s) returned."]
    if len(sample) < len(outcome.rows):
        notes.append(f"Showing the first {len(sample)} for narration.")
    if outcome.truncated:
        notes.append("The result set was truncated at the row cap — more rows exist.")
    return f"{table}\n\n{' '.join(notes)}"


def denial_narration(*, verdict: SqlVerdict, detail: str | None, sql: str) -> str:
    """The text shown when every attempt (including any repairs) was
    rejected. Templated, not model-generated — deliverable 4's own reasoning
    (TRACKER §5): a `REJECTED_*` verdict already carries the exact fact that
    needs saying, and asking the model to phrase it risks it narrating the
    refused SQL as if it had run.
    """
    reason = detail or "the statement was not a single read-only SELECT"
    return (
        "Mnemos did not run this query: the generated statement was refused by the "
        f"read-only SQL policy and was not executed. Reason: {reason}\n\n"
        f"Refused statement:\n```sql\n{sql}\n```"
    )


def execution_error_narration(outcome: ExecutionOutcome) -> str:
    """The text shown when a guard-`ALLOWED` statement failed *at* the
    database — a runtime error the guard has no way to see (an invented
    column, say), never a write: the guard already proved that. Templated
    for the same reason `denial_narration` is: there is no result set to
    narrate over honestly.
    """
    if outcome.error_code == "statement_timeout":
        return (
            "Mnemos ran this query but it did not finish in time and was cancelled. "
            f"Detail: {outcome.error_detail}"
        )
    return f"Mnemos ran this query but the database rejected it: {outcome.error_detail}"
