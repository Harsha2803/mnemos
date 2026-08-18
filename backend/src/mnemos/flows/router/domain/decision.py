"""Pure, deterministic routing policy for the three Phase-A answer flows.

The router is deliberately conservative: an ordinary question stays in chat
unless the text names document context or structured-data intent. This keeps
the zero-cost local path predictable and gives the application service a
fallback that cannot disappear with Ollama.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_TOKEN = re.compile(r"[a-z0-9_]+")

_DATABASE_TERMS = frozenset(
    {
        "analytics",
        "column",
        "columns",
        "database",
        "dataset",
        "datasource",
        "query",
        "row",
        "rows",
        "schema",
        "sql",
        "table",
        "tables",
        "warehouse",
    }
)
_DOCUMENT_TERMS = frozenset(
    {
        "citation",
        "citations",
        "contract",
        "document",
        "documents",
        "file",
        "files",
        "handbook",
        "manual",
        "memo",
        "policy",
        "report",
        "source",
        "sources",
        "upload",
        "uploaded",
    }
)
_DOCUMENT_PHRASES = (
    "according to",
    "from the document",
    "from our documents",
    "in the document",
    "in our files",
)
_BUSINESS_TERMS = frozenset(
    {
        "customer",
        "customers",
        "order",
        "orders",
        "product",
        "products",
        "region",
        "regions",
        "revenue",
        "sale",
        "sales",
    }
)
_ANALYSIS_TERMS = frozenset(
    {
        "average",
        "breakdown",
        "count",
        "how many",
        "metric",
        "metrics",
        "sell",
        "selling",
        "sold",
        "top",
        "total",
        "trend",
    }
)
_WRITE_TERMS = frozenset({"alter", "create", "delete", "drop", "insert", "truncate", "update"})
_TOOL_NOUNS = frozenset({"mcp", "tool"})
_TOOL_VERBS = frozenset({"call", "invoke", "run", "use"})


class RouteFlow(StrEnum):
    """The answer pipelines A4 is allowed to select."""

    CHAT = "chat"
    RAG = "rag"
    NL2SQL = "nl2sql"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """A selected flow plus a rationale safe and short enough for the transcript."""

    flow: RouteFlow
    reason: str


def classify_message(content: str) -> RouteDecision:
    """Select the narrowest flow clearly requested by ``content``.

    Explicit database vocabulary wins because it is unambiguous. Explicit
    document vocabulary comes next, before general business terms, so a
    request to summarise a sales report remains document retrieval rather
    than becoming a warehouse query. Business vocabulary needs an analysis
    or mutation signal; a casual mention of a customer therefore stays chat.
    """

    normalized = " ".join(content.casefold().split())
    tokens = frozenset(_TOKEN.findall(normalized))

    if tokens & _TOOL_NOUNS and tokens & _TOOL_VERBS:
        return RouteDecision(
            flow=RouteFlow.TOOL,
            reason="Requests one registered tool call.",
        )

    if tokens & _DATABASE_TERMS:
        return RouteDecision(
            flow=RouteFlow.NL2SQL,
            reason="Mentions database or SQL concepts.",
        )

    if tokens & _DOCUMENT_TERMS or any(phrase in normalized for phrase in _DOCUMENT_PHRASES):
        return RouteDecision(
            flow=RouteFlow.RAG,
            reason="Asks about documents or cited knowledge.",
        )

    if tokens & _WRITE_TERMS and tokens & _BUSINESS_TERMS:
        return RouteDecision(
            flow=RouteFlow.NL2SQL,
            reason="Requests an operation on structured data.",
        )

    has_analysis_intent = bool(tokens & _ANALYSIS_TERMS) or "how many" in normalized
    if has_analysis_intent and tokens & _BUSINESS_TERMS:
        return RouteDecision(
            flow=RouteFlow.NL2SQL,
            reason="Asks for a business metric or data breakdown.",
        )

    return RouteDecision(
        flow=RouteFlow.CHAT,
        reason="No document or database context is needed.",
    )
