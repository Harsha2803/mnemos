"""The control arm: naive concatenated-string prompt construction.

This is written to be a *fair* representative of how RAG prompts are normally built,
not a strawman. It does the things a competent engineer does on a first pass:
embed the query, take top-k by cosine, sort by score, join with newlines, and cut
to fit the window.

What it does not do — and what the comparison is actually measuring — is:

* enforce a token budget as an allocation problem rather than a truncation
* deduplicate overlapping chunks before they consume budget
* push authorization into the scan (the post-filter variant applies it after,
  which is the common "we added auth" implementation)
* distinguish a current belief from a superseded one
* record where any of it came from

The three variants exist so the benchmark can attribute each delta to a specific
missing mechanism rather than to "the baseline is bad".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .core import AuthorizationPredicate, Principal, Tokenizer
from .embed import Embedder, cosine_matrix
from .store import Store


@dataclass(slots=True)
class NaivePrompt:
    prompt: str
    tokens_consumed: int
    latency_ms: float
    included_chunk_ids: list[str]
    included_memory_ids: list[str]
    truncated: bool
    variant: str
    # Populated for measurement only. A real naive pipeline has no such record —
    # that absence is itself one of the findings.
    unauthorized_included: list[str] = field(default_factory=list)
    stale_included: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class NaiveContextBuilder:
    """Top-k retrieve, concatenate, truncate."""

    def __init__(self, store: Store, embedder: Embedder, tokenizer: Tokenizer) -> None:
        self.store = store
        self.embedder = embedder
        self.tokenizer = tokenizer

    def build(
        self,
        *,
        principal: Principal,
        query: str,
        token_budget: int,
        k: int = 12,
        system_prompt: str = "",
        variant: str = "naive",
    ) -> NaivePrompt:
        """
        Variants
        --------
        ``naive``            top-k, no authorization at all
        ``naive_postfilter`` top-k, then drop unauthorized results (post-filtering)
        ``naive_prefilter``  authorization applied in the scan, but still no budget
                             allocation, no dedup, and no belief-time filtering
        """
        started = time.perf_counter()
        predicate = AuthorizationPredicate.for_principal(principal)
        query_vec = self.embedder.encode([query])[0]

        chunks, matrix = self.store.all_chunks(principal.org_id)

        if variant == "naive_prefilter":
            keep = [
                i
                for i, c in enumerate(chunks)
                if predicate.allows(
                    org_id=c.org_id, workspace_id=c.workspace_id,
                    sensitivity=c.sensitivity, tags=c.tags,
                )
            ]
        else:
            keep = list(range(len(chunks)))

        if keep:
            sims = cosine_matrix(query_vec, matrix[keep])
            order = np.argsort(-sims)[: k * 2]
            selected = [chunks[keep[int(p)]] for p in order]
        else:
            selected = []

        if variant == "naive_postfilter":
            # Post-filtering: the classic mistake. Authorization is applied after
            # ranking has already truncated the pool, so the caller silently
            # receives fewer results than requested whenever the nearest
            # neighbours happen to be inaccessible.
            selected = [
                c
                for c in selected
                if predicate.allows(
                    org_id=c.org_id, workspace_id=c.workspace_id,
                    sensitivity=c.sensitivity, tags=c.tags,
                )
            ]

        selected = selected[:k]

        # Memory: every claim ever written, with no belief-time filter. This models
        # a store that appends facts and never marks them superseded, which is the
        # normal outcome when memory is "just another vector collection".
        claims = self.store.naive_all_claims(principal.org_id)
        if claims:
            cvecs = self.store.claim_vectors(claims)
            csims = cosine_matrix(query_vec, cvecs)
            corder = np.argsort(-csims)[:6]
            mem_selected = [claims[int(p)] for p in corder]
        else:
            mem_selected = []

        parts: list[str] = []
        if system_prompt:
            parts.append(system_prompt)
        for claim in mem_selected:
            parts.append(f"{claim.predicate.replace('_', ' ')}: {claim.object_text}")
        for chunk in selected:
            parts.append(chunk.content)
        parts.append(query)

        body = "\n\n".join(parts)

        truncated = False
        if self.tokenizer.count(body) > token_budget:
            truncated = True
            body = _hard_truncate(body, self.tokenizer, token_budget)

        # Which of the included items were actually still in the final string
        # after truncation? Truncation is blind, so this is not the same as
        # "what we selected" — and that gap is precisely what the gold-recall
        # metric detects.
        surviving_chunks = [c.id for c in selected if c.content[:60] in body]
        surviving_memory = [m.id for m in mem_selected if m.object_text[:40] in body]

        unauthorized = [
            c.id
            for c in selected
            if c.content[:60] in body
            and not predicate.allows(
                org_id=c.org_id, workspace_id=c.workspace_id,
                sensitivity=c.sensitivity, tags=c.tags,
            )
        ]
        stale = [
            m.id for m in mem_selected if m.retracted_at is not None and m.object_text[:40] in body
        ]

        return NaivePrompt(
            prompt=body,
            tokens_consumed=self.tokenizer.count(body),
            latency_ms=(time.perf_counter() - started) * 1000,
            included_chunk_ids=surviving_chunks,
            included_memory_ids=surviving_memory,
            truncated=truncated,
            variant=variant,
            unauthorized_included=unauthorized,
            stale_included=stale,
            metadata={"selected_chunks": len(selected), "selected_memory": len(mem_selected)},
        )


def _hard_truncate(text: str, tokenizer: Tokenizer, budget: int) -> str:
    """Cut to fit, the way a real naive pipeline does it.

    Binary search on character length against the token counter. There is no
    sentence-boundary awareness and no notion of which content mattered — whatever
    happens to be at the end is discarded. That is the behaviour being measured.
    """
    if tokenizer.count(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tokenizer.count(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]
