"""Retrieval operators, fusion, and deduplication.

Every operator returns the same `Candidate` envelope so that downstream passes
(fusion, dedup, conflict resolution, allocation) are written once rather than once
per source. Authorization is applied *inside* each scan, never after ranking.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from .core import (
    AuthorizationPredicate,
    MemoryKind,
    Sensitivity,
    Tokenizer,
    TrustTier,
    content_hash,
)
from .embed import Embedder, cosine_matrix
from .store import Chunk, Claim, Store


@dataclass(slots=True)
class Candidate:
    """Uniform retrieval result envelope."""

    id: str
    source_kind: str  # 'chunk' | 'memory'
    source_id: str
    text: str
    score: float
    operator_id: str
    token_count: int
    trust_tier: TrustTier
    sensitivity: Sensitivity
    acl_rule_id: str
    content_hash: str
    section: str
    #: Calibrated expected usefulness in [0, 1]. Distinct from `score`, which is
    #: whatever the producing operator emitted (cosine, BM25, or a fused rank
    #: score) and is neither comparable across operators nor usable as a magnitude.
    utility: float = 0.0
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    # Bitemporal provenance, carried so conflict resolution and the staleness
    # metric can reason about it without a second database round trip.
    valid_from: datetime | None = None
    recorded_at: datetime | None = None
    subject_id: str | None = None
    predicate: str | None = None


@dataclass(slots=True)
class OperatorResult:
    operator_id: str
    candidates: list[Candidate]
    latency_ms: float
    scanned: int
    admitted: int
    denied_by_acl: int
    denied_by_currency: int = 0
    degraded: bool = False
    degradation_reason: str | None = None


class RetrievalEngine:
    def __init__(self, store: Store, embedder: Embedder, tokenizer: Tokenizer) -> None:
        self.store = store
        self.embedder = embedder
        self.tokenizer = tokenizer

    # -- operators ----------------------------------------------------------

    def vector_search_chunks(
        self,
        *,
        query_vec: np.ndarray,
        predicate: AuthorizationPredicate,
        k: int,
        operator_id: str = "vector_search_chunks",
    ) -> OperatorResult:
        """ANN over document chunks with the ACL predicate pushed into the scan.

        Filtering happens before ranking truncates the candidate set. Post-filtering
        would return fewer results than the caller asked for whenever the nearest
        neighbours are inaccessible, silently degrading recall — the exact failure
        the benchmark's authorization metric detects.
        """
        started = time.perf_counter()
        chunks, matrix = self.store.all_chunks(predicate.org_id)
        scanned = len(chunks)

        authorized = [
            i
            for i, c in enumerate(chunks)
            if predicate.allows(
                org_id=c.org_id,
                workspace_id=c.workspace_id,
                sensitivity=c.sensitivity,
                tags=c.tags,
            )
        ]
        denied = scanned - len(authorized)
        # Currency filter, applied in the scan alongside authorization: a chunk
        # belonging to a superseded revision of a document is not a lower-ranked
        # result, it is a wrong one. Ranking cannot fix it because the obsolete
        # text is often a *better* lexical match than the current text.
        keep = [i for i in authorized if not chunks[i].doc_superseded]
        stale_denied = len(authorized) - len(keep)

        if not keep:
            return OperatorResult(operator_id, [], _ms(started), scanned, 0, denied,
                                  stale_denied)

        sims = cosine_matrix(query_vec, matrix[keep])
        order = np.argsort(-sims)[:k]

        out: list[Candidate] = []
        for rank, pos in enumerate(order):
            c = chunks[keep[int(pos)]]
            out.append(
                Candidate(
                    id=f"chunk:{c.id}",
                    source_kind="chunk",
                    source_id=c.id,
                    text=c.content,
                    score=float(sims[int(pos)]),
                    operator_id=operator_id,
                    token_count=c.token_count,
                    trust_tier=c.trust_tier,
                    sensitivity=c.sensitivity,
                    acl_rule_id=predicate.rule_id,
                    content_hash=content_hash(c.content),
                    section="documents",
                    rank=rank,
                    metadata={
                        "document_id": c.document_id,
                        "document_title": c.document_title,
                        "page": c.page,
                        "char_start": c.char_start,
                        "char_end": c.char_end,
                        "heading": c.heading,
                    },
                )
            )
        return OperatorResult(operator_id, out, _ms(started), scanned, len(out), denied,
                              stale_denied)

    def lexical_search_chunks(
        self,
        *,
        query: str,
        predicate: AuthorizationPredicate,
        k: int,
        operator_id: str = "lexical_search_chunks",
    ) -> OperatorResult:
        """BM25-style keyword scan, also ACL-filtered before ranking."""
        started = time.perf_counter()
        chunks, _ = self.store.all_chunks(predicate.org_id)
        scanned = len(chunks)

        authorized = [
            c
            for c in chunks
            if predicate.allows(
                org_id=c.org_id,
                workspace_id=c.workspace_id,
                sensitivity=c.sensitivity,
                tags=c.tags,
            )
        ]
        denied = scanned - len(authorized)
        allowed = [c for c in authorized if not c.doc_superseded]
        stale_denied = len(authorized) - len(allowed)
        scored = _bm25(query, [c.content for c in allowed])
        order = np.argsort(-scored)[:k]

        out: list[Candidate] = []
        for rank, pos in enumerate(order):
            if scored[int(pos)] <= 0:
                continue
            c = allowed[int(pos)]
            out.append(
                Candidate(
                    id=f"chunk:{c.id}",
                    source_kind="chunk",
                    source_id=c.id,
                    text=c.content,
                    score=float(scored[int(pos)]),
                    operator_id=operator_id,
                    token_count=c.token_count,
                    trust_tier=c.trust_tier,
                    sensitivity=c.sensitivity,
                    acl_rule_id=predicate.rule_id,
                    content_hash=content_hash(c.content),
                    section="documents",
                    rank=rank,
                    metadata={
                        "document_id": c.document_id,
                        "document_title": c.document_title,
                        "page": c.page,
                        "char_start": c.char_start,
                        "char_end": c.char_end,
                    },
                )
            )
        return OperatorResult(operator_id, out, _ms(started), scanned, len(out), denied,
                              stale_denied)

    def memory_scan(
        self,
        *,
        query_vec: np.ndarray,
        predicate: AuthorizationPredicate,
        k: int,
        as_of: datetime | None = None,
        believed_at: datetime | None = None,
        kinds: tuple[MemoryKind, ...] | None = None,
        operator_id: str = "memory_scan",
    ) -> OperatorResult:
        """Bitemporal claim retrieval.

        `as_of` / `believed_at` are passed straight through to the store, so a
        compilation can be replayed against the system's historical beliefs. This
        is what makes superseded facts structurally unreachable rather than merely
        deprioritised.
        """
        started = time.perf_counter()
        claims = self.store.query_claims(
            org_id=predicate.org_id, as_of=as_of, believed_at=believed_at, kinds=kinds
        )
        scanned = len(claims)
        allowed = [
            c
            for c in claims
            if predicate.allows(
                org_id=c.org_id,
                workspace_id=c.workspace_id,
                sensitivity=c.sensitivity,
                tags=c.tags,
            )
        ]
        denied = scanned - len(allowed)
        if not allowed:
            return OperatorResult(operator_id, [], _ms(started), scanned, 0, denied)

        matrix = self.store.claim_vectors(allowed)
        sims = cosine_matrix(query_vec, matrix)
        order = np.argsort(-sims)[:k]

        out: list[Candidate] = []
        for rank, pos in enumerate(order):
            c = allowed[int(pos)]
            text = f"{c.predicate.replace('_', ' ')}: {c.object_text}"
            out.append(
                Candidate(
                    id=f"memory:{c.id}",
                    source_kind="memory",
                    source_id=c.id,
                    text=text,
                    score=float(sims[int(pos)]),
                    operator_id=operator_id,
                    token_count=self.tokenizer.count(text),
                    trust_tier=c.trust_tier,
                    sensitivity=c.sensitivity,
                    acl_rule_id=predicate.rule_id,
                    content_hash=content_hash(text),
                    section="memory",
                    rank=rank,
                    valid_from=c.valid_from,
                    recorded_at=c.recorded_at,
                    subject_id=c.subject_id,
                    predicate=c.predicate,
                    metadata={"kind": str(c.kind), "confidence": c.confidence},
                )
            )
        return OperatorResult(operator_id, out, _ms(started), scanned, len(out), denied)


# ---------------------------------------------------------------------------
# Fusion and refinement
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    results: list[OperatorResult], k: int = 60
) -> list[Candidate]:
    """Fuse heterogeneous rankings.

    RRF is used rather than score normalisation because cosine similarity and BM25
    produce score distributions that are not comparable on any common scale. RRF
    depends only on rank, so it is immune to that mismatch.
    """
    fused: dict[str, Candidate] = {}
    accum: dict[str, float] = {}
    for res in results:
        for rank, cand in enumerate(res.candidates):
            accum[cand.id] = accum.get(cand.id, 0.0) + 1.0 / (k + rank + 1)
            if cand.id not in fused:
                fused[cand.id] = cand
    for cid, score in accum.items():
        fused[cid].score = score
    return sorted(fused.values(), key=lambda c: (-c.score, c.id))


def calibrate_utility(candidates: list[Candidate], tau: float = 6.0) -> list[Candidate]:
    """Convert fused ranks into a utility magnitude the allocator can spend against.

    This step is not cosmetic — omitting it silently breaks the allocator.

    RRF scores compress into a narrow band (with k=60 a 40-candidate pool spans
    roughly 0.0143 to 0.0164). Feeding that into a `utility / tokens` density means
    the numerator is effectively constant and the ranking degenerates to `1 / tokens`
    — the allocator buys the *shortest* passages available, which in any real corpus
    are headings and boilerplate footers rather than answers.

    Exponential decay over rank restores a usable dynamic range: rank 0 scores 1.0,
    rank 6 about 0.37, rank 18 about 0.05. A short boilerplate line ranked 20th can
    no longer outbid the answer-bearing passage ranked 1st merely by being cheap.
    """
    for rank, cand in enumerate(sorted(candidates, key=lambda c: (-c.score, c.id))):
        cand.utility = float(np.exp(-rank / tau))
    return candidates


@dataclass(slots=True)
class DedupReport:
    removed: int
    tokens_saved: int
    pairs: list[tuple[str, str]] = field(default_factory=list)


def deduplicate(
    candidates: list[Candidate], threshold: float = 0.86
) -> tuple[list[Candidate], DedupReport]:
    """Exact then near-duplicate collapse.

    Chunked documents overlap by construction, and top-k retrieval over them returns
    the same sentences repeatedly. Those repeated tokens are charged against the
    budget and buy nothing, which is one of the largest measurable wins over naive
    concatenation.

    Near-duplication uses token-set Jaccard: cheap, explainable, and adequate for
    the overlap that chunking actually produces.
    """
    kept: list[Candidate] = []
    seen_hashes: set[str] = set()
    seen_tokens: list[tuple[str, set[str]]] = []
    removed = 0
    tokens_saved = 0
    pairs: list[tuple[str, str]] = []

    for cand in candidates:
        if cand.content_hash in seen_hashes:
            removed += 1
            tokens_saved += cand.token_count
            pairs.append((cand.id, "exact"))
            continue

        toks = set(_words(cand.text))
        duplicate_of: str | None = None
        for other_id, other_toks in seen_tokens:
            if not toks or not other_toks:
                continue
            jaccard = len(toks & other_toks) / len(toks | other_toks)
            if jaccard >= threshold:
                duplicate_of = other_id
                break

        if duplicate_of:
            removed += 1
            tokens_saved += cand.token_count
            pairs.append((cand.id, duplicate_of))
            continue

        seen_hashes.add(cand.content_hash)
        seen_tokens.append((cand.id, toks))
        kept.append(cand)

    return kept, DedupReport(removed=removed, tokens_saved=tokens_saved, pairs=pairs)


@dataclass(slots=True)
class ConflictReport:
    resolved: int
    demoted_ids: list[str] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)


def resolve_conflicts(candidates: list[Candidate]) -> tuple[list[Candidate], ConflictReport]:
    """Arbitrate contradictory claims about the same (subject, predicate).

    Ordering: higher trust (lower tier number) wins, then later `valid_from`, then
    later `recorded_at`, then a deterministic tiebreak on id so the result is stable.

    Losers are demoted, not silently dropped — the caller can surface "a conflicting
    earlier belief exists". Discarding contradictions without trace is how systems
    become confidently wrong.
    """
    groups: dict[tuple[str, str], list[Candidate]] = {}
    passthrough: list[Candidate] = []
    for c in candidates:
        if c.source_kind == "memory" and c.subject_id and c.predicate:
            groups.setdefault((c.subject_id, c.predicate), []).append(c)
        else:
            passthrough.append(c)

    kept: list[Candidate] = []
    report = ConflictReport(resolved=0)
    for (subject, predicate), members in groups.items():
        if len(members) == 1:
            kept.append(members[0])
            continue
        ranked = sorted(
            members,
            key=lambda c: (
                int(c.trust_tier),
                -(c.valid_from.timestamp() if c.valid_from else 0.0),
                -(c.recorded_at.timestamp() if c.recorded_at else 0.0),
                c.id,
            ),
        )
        winner, losers = ranked[0], ranked[1:]
        kept.append(winner)
        report.resolved += len(losers)
        report.demoted_ids.extend(x.id for x in losers)
        report.details.append(
            {
                "subject": subject,
                "predicate": predicate,
                "winner": winner.id,
                "demoted": [x.id for x in losers],
                "reason": "higher_trust_then_later_validity",
            }
        )
    return passthrough + kept, report


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _bm25(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    """Standard BM25. Implemented directly to avoid a dependency for ~20 lines."""
    if not docs:
        return np.zeros(0, dtype=np.float32)
    tokenized = [_words(d) for d in docs]
    lengths = np.array([len(t) for t in tokenized], dtype=np.float32)
    avgdl = float(lengths.mean()) if lengths.size else 1.0
    n = len(docs)
    scores = np.zeros(n, dtype=np.float32)

    for term in set(_words(query)):
        containing = [i for i, toks in enumerate(tokenized) if term in toks]
        if not containing:
            continue
        df = len(containing)
        idf = float(np.log(1.0 + (n - df + 0.5) / (df + 0.5)))
        for i in containing:
            tf = tokenized[i].count(term)
            denom = tf + k1 * (1 - b + b * (lengths[i] / max(avgdl, 1e-6)))
            scores[i] += idf * (tf * (k1 + 1)) / max(denom, 1e-6)
    return scores
