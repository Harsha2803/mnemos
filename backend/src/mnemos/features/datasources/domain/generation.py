"""The NL2SQL system prompt and the pure text-shaping around it.

Kept to a prompt constant and a completion-to-SQL extractor, no `ChatModel`
call — the same split `flows/rag/domain/prompt.py` uses: `domain/` shapes
text, `application/` is where a port actually gets called. Turn assembly
(`ChatTurn(role=..., content=...)`) stays in `application/generation.py`
for the same reason RAG's turn list is built in `RagFlow`, not in its
`domain/prompt.py` — a `ChatTurn` is a fact about talking to a model, not
about what the words say.
"""

from __future__ import annotations

import re

NL2SQL_SYSTEM_PROMPT = (
    "You are Mnemos, translating a question about an organisation's data warehouse "
    "into Postgres SQL. You will be shown the warehouse's schema and business "
    "glossary below. Write exactly one read-only SELECT statement that answers the "
    "question — never INSERT, UPDATE, DELETE, or any statement that modifies data "
    "or schema, and never more than one statement. Use only the tables and columns "
    "shown; do not invent any. Respond with the SQL statement alone, inside a single "
    "```sql code fence, and nothing else — no explanation before or after it."
)

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def build_repair_prompt(*, previous_sql: str, detail: str | None) -> str:
    """The user turn a repair attempt (deliverable 4, `Settings.
    sql_repair_attempts`) adds after a rejected candidate, telling the model
    exactly what it wrote and exactly why the guard would not run it.

    Deliberately quotes `detail` verbatim rather than paraphrasing it — the
    guard's own wording ("contains Insert — Mnemos only reads") is already
    the most precise available description of the problem, and paraphrasing
    it risks losing the specific node/table name a repair needs to fix.
    """
    reason = detail or "it was not a single read-only SELECT statement"
    return (
        "That statement was rejected by Mnemos's read-only SQL guard.\n\n"
        f"Reason: {reason}\n\n"
        "Write a corrected, single read-only SELECT statement that still answers "
        "the original question. Respond with the SQL statement alone, inside a "
        "single ```sql code fence, and nothing else — no explanation before or "
        "after it."
    )


def extract_sql_statement(response_text: str) -> str:
    """Pull the candidate statement out of the model's raw completion text.

    The system prompt asks for exactly one fenced ```sql block and nothing
    else, but a small local model does not always comply. Falls back to the
    whole trimmed response when no fence is found — extraction does not need
    to be clever, because `guard.guard_sql`'s parse step is what actually
    decides safety, and a response that is not SQL at all correctly ends up
    `rejected_unparseable` either way.
    """
    match = _FENCE.search(response_text)
    candidate = match.group(1) if match else response_text
    return candidate.strip().rstrip(";").strip()
