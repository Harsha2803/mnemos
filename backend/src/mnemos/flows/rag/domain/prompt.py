"""Pure functions: turning retrieved chunks into a prompt, and an answer back
into citations. No I/O, no ORM — the same layering rule `features/*/domain`
follows, here inside a flow because a flow is where retrieval (`features/
knowledge`) and conversation (`features/chat`) meet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mnemos.features.knowledge.domain import RetrievedChunk, Tokenizer

RAG_SYSTEM_PROMPT = (
    "You are Mnemos, an enterprise AI assistant answering from the organisation's "
    "uploaded documents. Below are numbered source passages. Answer using only "
    "what they support, and cite the passage number in square brackets — like "
    "[1] — immediately after any claim it supports. If the passages do not answer "
    "the question, say plainly that you could not find supporting documents rather "
    "than guessing."
)

NO_DOCUMENTS_FOUND = (
    "No relevant documents were found in the knowledge base for this question. "
    "Tell the user plainly that you found no supporting documents, rather than "
    "answering as if you had."
)

_MARKER = re.compile(r"\[(\d+)\]")


def truncate_to_budget(
    chunks: list[RetrievedChunk], tokenizer: Tokenizer, *, budget_tokens: int
) -> list[RetrievedChunk]:
    """Greedy, in the order retrieval already fused and deduped them — not
    the section-floored allocator `C4` builds, see `TRACKER §5`'s "explicitly
    not in A2"."""
    admitted: list[RetrievedChunk] = []
    spent = 0
    for chunk in chunks:
        cost = chunk.token_count
        if spent + cost > budget_tokens:
            continue
        admitted.append(chunk)
        spent += cost
    return admitted


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Numbered passages, 1-indexed to match the citation markers the system
    prompt asks the model to emit."""
    if not chunks:
        return NO_DOCUMENTS_FOUND
    parts = [
        f"[{i}] (from {chunk.document_title}) {chunk.text}" for i, chunk in enumerate(chunks, 1)
    ]
    return "\n\n".join(parts)


@dataclass(frozen=True, slots=True)
class CitationTarget:
    marker: int
    chunk: RetrievedChunk


def extract_citations(answer_text: str, chunks: list[RetrievedChunk]) -> list[CitationTarget]:
    """Every `[n]` in the answer that names a chunk actually offered — an
    invented marker (the model citing `[7]` out of three passages) is dropped
    rather than trusted, because a citation pointing at nothing is worse than
    none."""
    seen: dict[int, CitationTarget] = {}
    for match in _MARKER.finditer(answer_text):
        marker = int(match.group(1))
        if marker in seen or not (1 <= marker <= len(chunks)):
            continue
        seen[marker] = CitationTarget(marker=marker, chunk=chunks[marker - 1])
    return [seen[m] for m in sorted(seen)]
