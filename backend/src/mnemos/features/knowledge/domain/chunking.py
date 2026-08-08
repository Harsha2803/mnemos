"""Structure-aware chunking with character offsets.

Ported from `_v1/ingest.py`'s `chunk_text`. Offsets into the *original*
extracted text are what let a citation resolve to an exact highlighted span
in the source rather than "somewhere in this document" — without them the
click-through citations deliverable 6 asks for cannot exist.

Overlap between chunks is deliberate: it prevents an answer that straddles a
paragraph boundary from being lost to a chunk edge, at the cost of some
duplicate text — which `deduplicate` (`retrieval.py`) removes downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mnemos.features.knowledge.domain.tokenizer import Tokenizer

_HEADING = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Z0-9 ,\-/&']{6,}\s*)$")
_PARA_SPLIT = re.compile(r"\n\s*\n")


@dataclass(slots=True)
class RawChunk:
    ordinal: int
    content: str
    char_start: int
    char_end: int
    token_count: int
    heading: str | None
    page: int | None


def chunk_text(
    text: str,
    tokenizer: Tokenizer,
    *,
    target_tokens: int = 120,
    overlap_tokens: int = 24,
    page: int | None = None,
) -> list[RawChunk]:
    """Split on paragraph boundaries, packing up to `target_tokens`."""
    chunks: list[RawChunk] = []
    heading: str | None = None
    cursor = 0
    buf: list[tuple[str, int, int]] = []
    buf_tokens = 0
    ordinal = 0

    def flush() -> None:
        nonlocal buf, buf_tokens, ordinal
        if not buf:
            return
        content = "\n\n".join(p for p, _, _ in buf).strip()
        if content:
            chunks.append(
                RawChunk(
                    ordinal=ordinal,
                    content=content,
                    char_start=buf[0][1],
                    char_end=buf[-1][2],
                    token_count=tokenizer.count(content),
                    heading=heading,
                    page=page,
                )
            )
            ordinal += 1
        if overlap_tokens > 0 and buf:
            tail = buf[-1]
            if tokenizer.count(tail[0]) <= overlap_tokens * 2:
                buf = [tail]
                buf_tokens = tokenizer.count(tail[0])
                return
        buf = []
        buf_tokens = 0

    for para in _PARA_SPLIT.split(text):
        stripped = para.strip()
        if not stripped:
            cursor += len(para) + 2
            continue
        start = text.find(stripped, cursor)
        if start < 0:
            start = cursor
        end = start + len(stripped)
        cursor = end

        if _HEADING.match(stripped) and len(stripped) < 90:
            flush()
            heading = stripped.lstrip("# ").strip()
            continue

        cost = tokenizer.count(stripped)
        if buf_tokens + cost > target_tokens and buf:
            flush()
        buf.append((stripped, start, end))
        buf_tokens += cost

    flush()
    return chunks
