"""Fusion and deduplication over retrieved chunks.

Ported from `_v1/retrieval.py`'s `reciprocal_rank_fusion` and `deduplicate`.
The operators that *produce* candidates (vector, lexical) are SQL now — pgvector
HNSW and pg_trgm, in `adapters/retrieval.py` — because the ACL and currency
predicates have to be pushed into the scan (C4) and a Python-side brute-force
scan cannot do that at any real corpus size (§4 item 3). Fusion and dedup stay
pure Python: both operate on the small candidate set each operator already
returned, not on the corpus.

**Not ported here:** `calibrate_utility` and `resolve_conflicts` from `_v1`.
Utility calibration feeds a budget allocator with section floors that does not
exist yet (`C4`); this milestone truncates to a token budget in fused-score
order instead, which is honest about being simpler rather than a stub of the
real allocator. Conflict resolution arbitrates contradictory *memory* claims,
which `A2` does not retrieve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from mnemos.features.knowledge.domain.ids import ChunkId, DocumentId


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """Uniform envelope both the vector and lexical operators return."""

    chunk_id: ChunkId
    document_id: DocumentId
    document_title: str
    text: str
    score: float
    operator_id: str
    token_count: int
    char_start: int
    char_end: int
    page_number: int | None


@dataclass(slots=True)
class FusedChunk:
    chunk: RetrievedChunk
    rrf_score: float


def reciprocal_rank_fusion(
    operator_results: list[list[RetrievedChunk]], *, k: int = 60
) -> list[FusedChunk]:
    """Fuse heterogeneous rankings (vector, lexical) by rank rather than raw
    score — cosine similarity and pg_trgm similarity are not on a comparable
    scale, and RRF depends only on rank, so it is immune to that mismatch."""
    accum: dict[UUID, float] = {}
    by_id: dict[UUID, RetrievedChunk] = {}
    for results in operator_results:
        for rank, candidate in enumerate(results):
            accum[candidate.chunk_id] = accum.get(candidate.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            by_id.setdefault(candidate.chunk_id, candidate)
    fused = [FusedChunk(chunk=by_id[cid], rrf_score=score) for cid, score in accum.items()]
    fused.sort(key=lambda f: (-f.rrf_score, str(f.chunk.chunk_id)))
    return fused


@dataclass(slots=True)
class DedupReport:
    removed: int = 0
    tokens_saved: int = 0
    duplicate_of: dict[UUID, UUID] = field(default_factory=dict)


_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def deduplicate(
    fused: list[FusedChunk], *, threshold: float = 0.86
) -> tuple[list[FusedChunk], DedupReport]:
    """Near-duplicate collapse by token-set Jaccard similarity.

    Chunked documents overlap by construction (the chunker's `overlap_tokens`),
    and top-k retrieval over them returns the same sentences repeatedly. Those
    repeated tokens are charged against the prompt budget and buy nothing —
    one of the largest measurable wins over naive concatenation (README).
    """
    kept: list[FusedChunk] = []
    seen: list[tuple[UUID, set[str]]] = []
    report = DedupReport()

    for item in fused:
        toks = _words(item.chunk.text)
        duplicate_of: UUID | None = None
        for other_id, other_toks in seen:
            if not toks or not other_toks:
                continue
            jaccard = len(toks & other_toks) / len(toks | other_toks)
            if jaccard >= threshold:
                duplicate_of = other_id
                break
        if duplicate_of is not None:
            report.removed += 1
            report.tokens_saved += item.chunk.token_count
            report.duplicate_of[item.chunk.chunk_id] = duplicate_of
            continue
        seen.append((item.chunk.chunk_id, toks))
        kept.append(item)

    return kept, report


def truncate_to_budget(fused: list[FusedChunk], *, budget_tokens: int) -> list[RetrievedChunk]:
    """Greedy, in fused-score order, until the next chunk would overshoot.

    Not the allocator `C4` builds (utility density, section floors) — a
    straightforward truncation, which is what `A2` needs and no more (see the
    module docstring for what is deliberately not ported yet)."""
    admitted: list[RetrievedChunk] = []
    spent = 0
    for item in fused:
        cost = item.chunk.token_count
        if spent + cost > budget_tokens:
            continue
        admitted.append(item.chunk)
        spent += cost
    return admitted
