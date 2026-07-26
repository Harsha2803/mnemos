"""Benchmark: naive concatenated-string prompt vs compiled context object.

Six metrics, all computed locally with no LLM judge and no paid API. Each isolates
one mechanism, so a delta can be attributed rather than hand-waved.

======================  ====================================================
Metric                  What it detects
======================  ====================================================
answer_retention        Did the answer-bearing text survive into the prompt
                        at this budget? The headline quality metric.
budget_overrun          Fraction of prompts exceeding the stated token budget.
duplicate_waste         Share of prompt tokens that are near-duplicate text.
acl_leak_rate           Prompts containing content the principal may not see.
stale_fact_rate         Prompts containing a superseded belief.
provenance              Fraction of included content traceable to a source.
======================  ====================================================

Latency is reported but deliberately *not* framed as a win: the compiler does more
work and is slower. The question the table answers is what that cost buys.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .baseline import NaiveContextBuilder
from .compiler import Budgets, ContextCompiler, ContextRequest, SectionSpec
from .core import (
    HeuristicTokenizer,
    MemoryKind,
    Principal,
    Sensitivity,
    Settings,
    Tokenizer,
    TrustTier,
)
from .dataset import (
    DOCUMENTS,
    MEMORY_QUESTION,
    ORG_ID,
    OUTDATED_MARKERS,
    QUESTIONS,
    SEED_CLAIMS,
    STALE_VALUE,
    SUPERSEDED_DOCUMENTS,
    USER_ID,
    WORKSPACE,
    Question,
)
from .embed import build_embedder
from .ingest import Ingestor
from .retrieval import RetrievalEngine, _words
from .store import Store

SYSTEM_PROMPT = (
    "You are Northwind's internal assistant. Answer only from the provided context. "
    "If the context does not contain the answer, say so."
)


@dataclass(slots=True)
class ArmResult:
    name: str
    answer_retention: float
    budget_overrun_rate: float
    mean_tokens: float
    p95_tokens: int
    duplicate_waste: float
    acl_leak_rate: float
    stale_fact_rate: float
    outdated_doc_rate: float
    provenance: float
    mean_latency_ms: float
    p95_latency_ms: float
    detail: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Corpus construction
# ---------------------------------------------------------------------------


def build_corpus(settings: Settings, db_path: str = ":memory:") -> tuple[Store, Any, Tokenizer]:
    tokenizer = HeuristicTokenizer()
    embedder = build_embedder(settings.embedder, settings.embedding_dim)
    store = Store(db_path, dim=embedder.dim)
    ingestor = Ingestor(store, embedder, tokenizer)

    for doc in DOCUMENTS:
        ingestor.ingest_text(
            org_id=ORG_ID,
            title=doc.title,
            source_uri=f"internal://{doc.key}",
            text=doc.body,
            sensitivity=doc.sensitivity,
            trust_tier=doc.trust_tier,
            tags=doc.tags,
            workspace_id=WORKSPACE,
        )

    # Prior-year revisions live in the same corpus, exactly as they do on a real
    # document share. Nobody deletes last year's handbook.
    for doc in SUPERSEDED_DOCUMENTS:
        ingestor.ingest_text(
            org_id=ORG_ID,
            title=doc.title,
            source_uri=f"internal://archive/{doc.key}",
            text=doc.body,
            sensitivity=doc.sensitivity,
            trust_tier=doc.trust_tier,
            tags=doc.tags,
            workspace_id=WORKSPACE,
            superseded=True,
        )

    for seed in SEED_CLAIMS:
        vec = embedder.encode([f"{seed.predicate} {seed.object_text}"])[0]
        store.write_claim(
            org_id=ORG_ID,
            kind=seed.kind,
            subject_id=seed.subject_id,
            predicate=seed.predicate,
            object_text=seed.object_text,
            vector=vec,
            valid_from=seed.valid_from,
            sensitivity=seed.sensitivity,
            trust_tier=seed.trust_tier,
            salience=seed.salience,
            workspace_id=WORKSPACE,
        )
    return store, embedder, tokenizer


def demo_principal() -> Principal:
    """A normal employee: cleared to CONFIDENTIAL, not to RESTRICTED payroll."""
    return Principal(
        org_id=ORG_ID,
        user_id=USER_ID,
        workspaces=frozenset({WORKSPACE}),
        max_sensitivity=Sensitivity.CONFIDENTIAL,
        denied_tags=frozenset({"payroll"}),
    )


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Collapse whitespace before matching.

    Source documents wrap lines; an answer string that reads
    "capped at five working days" appears in the corpus as
    "capped at\nfive working days". Matching on raw text silently scored those
    questions as unanswerable for *every* arm, which capped the headline metric
    at 13/23 and made the comparison meaningless. A newline is not a semantic
    difference, so normalisation happens on both sides of the comparison.
    """
    return _WS.sub(" ", text)


def _contains(haystack: str, needle: str) -> bool:
    return _norm(needle) in _norm(haystack)


def _duplicate_waste(prompt: str, window: int = 12) -> float:
    """Fraction of tokens belonging to a repeated n-gram.

    Shingling at n=12 catches genuinely repeated passages (boilerplate footers,
    overlapping chunk tails) while ignoring the incidental repetition of common
    phrases that any English text contains.
    """
    tokens = _words(prompt)
    if len(tokens) <= window:
        return 0.0
    seen: set[tuple[str, ...]] = set()
    duplicated = 0
    i = 0
    while i <= len(tokens) - window:
        gram = tuple(tokens[i : i + window])
        if gram in seen:
            duplicated += window
            i += window
        else:
            seen.add(gram)
            i += 1
    return duplicated / len(tokens)


def _restricted_markers() -> list[str]:
    """Distinctive strings that only appear in the RESTRICTED payroll document."""
    return [
        "118,000 to 146,000 EUR",
        "149,000 to 188,000 EUR",
        "location factor for the Berlin hub is 1.00",
        "Equity refresh for E6",
    ]


def _acl_leaked(prompt: str) -> bool:
    return any(_contains(prompt, marker) for marker in _restricted_markers())


def _stale_present(prompt: str) -> bool:
    return _contains(prompt, STALE_VALUE)


def _outdated_present(prompt: str) -> bool:
    """Does the prompt contain a figure that only exists in a superseded revision?"""
    return any(_contains(prompt, m) for m in OUTDATED_MARKERS)


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------


def run_naive(
    store: Store,
    embedder: Any,
    tokenizer: Tokenizer,
    questions: list[Question],
    budget: int,
    variant: str,
    k: int = 12,
) -> ArmResult:
    builder = NaiveContextBuilder(store, embedder, tokenizer)
    principal = demo_principal()

    retained = 0
    overruns = 0
    tokens: list[int] = []
    latencies: list[float] = []
    dup: list[float] = []
    leaks = 0
    stale = 0
    outdated = 0
    detail: list[dict[str, Any]] = []

    for q in questions:
        out = builder.build(
            principal=principal, query=q.query, token_budget=budget,
            k=k, system_prompt=SYSTEM_PROMPT, variant=variant,
        )
        hit = _contains(out.prompt, q.answer_key)
        retained += int(hit)
        over = out.tokens_consumed > budget
        overruns += int(over)
        tokens.append(out.tokens_consumed)
        latencies.append(out.latency_ms)
        dup.append(_duplicate_waste(out.prompt))
        leaked = _acl_leaked(out.prompt)
        leaks += int(leaked)
        is_stale = _stale_present(out.prompt)
        stale += int(is_stale)
        is_outdated = _outdated_present(out.prompt)
        outdated += int(is_outdated)
        detail.append({
            "qid": q.qid, "retained": hit, "tokens": out.tokens_consumed,
            "over_budget": over, "acl_leak": leaked, "stale": is_stale,
            "outdated_doc": is_outdated, "truncated": out.truncated,
        })

    n = len(questions)
    return ArmResult(
        name=variant,
        answer_retention=retained / n,
        budget_overrun_rate=overruns / n,
        mean_tokens=statistics.mean(tokens),
        p95_tokens=_p95(tokens),
        duplicate_waste=statistics.mean(dup),
        acl_leak_rate=leaks / n,
        stale_fact_rate=stale / n,
        outdated_doc_rate=outdated / n,
        provenance=0.0,  # a concatenated string carries no manifest, by construction
        mean_latency_ms=statistics.mean(latencies),
        p95_latency_ms=_p95(latencies),
        detail=detail,
    )


def run_compiled(
    store: Store,
    embedder: Any,
    tokenizer: Tokenizer,
    settings: Settings,
    questions: list[Question],
    budget: int,
) -> ArmResult:
    engine = RetrievalEngine(store, embedder, tokenizer)
    compiler = ContextCompiler(engine, embedder, tokenizer, settings)
    principal = demo_principal()

    sections = [
        SectionSpec("memory", floor_tokens=60, ceil_tokens=max(200, budget // 5), priority=10),
        SectionSpec("documents", floor_tokens=0, ceil_tokens=budget, priority=5),
    ]

    retained = 0
    overruns = 0
    tokens: list[int] = []
    latencies: list[float] = []
    dup: list[float] = []
    leaks = 0
    stale = 0
    outdated = 0
    provenance: list[float] = []
    detail: list[dict[str, Any]] = []

    for q in questions:
        req = ContextRequest(
            principal=principal, query=q.query,
            budgets=Budgets(tokens=budget), sections=sections,
            system_prompt=SYSTEM_PROMPT,
        )
        bundle = compiler.compile(req)
        hit = _contains(bundle.prompt, q.answer_key)
        retained += int(hit)
        over = bundle.tokens_consumed > budget
        overruns += int(over)
        tokens.append(bundle.tokens_consumed)
        latencies.append(bundle.latency_ms)
        dup.append(_duplicate_waste(bundle.prompt))
        leaked = _acl_leaked(bundle.prompt)
        leaks += int(leaked)
        is_stale = _stale_present(bundle.prompt)
        stale += int(is_stale)
        is_outdated = _outdated_present(bundle.prompt)
        outdated += int(is_outdated)
        # Every manifest entry names a source id, an operator and an ACL rule.
        provenance.append(1.0 if bundle.manifest else 0.0)
        detail.append({
            "qid": q.qid, "retained": hit, "tokens": bundle.tokens_consumed,
            "over_budget": over, "acl_leak": leaked, "stale": is_stale,
            "outdated_doc": is_outdated,
            "manifest_items": len(bundle.manifest),
            "evicted": bundle.budget_report["evicted"],
            "digest": bundle.digest[:19],
        })

    n = len(questions)
    return ArmResult(
        name="mnemos_compiled",
        answer_retention=retained / n,
        budget_overrun_rate=overruns / n,
        mean_tokens=statistics.mean(tokens),
        p95_tokens=_p95(tokens),
        duplicate_waste=statistics.mean(dup),
        acl_leak_rate=leaks / n,
        stale_fact_rate=stale / n,
        outdated_doc_rate=outdated / n,
        provenance=statistics.mean(provenance),
        mean_latency_ms=statistics.mean(latencies),
        p95_latency_ms=_p95(latencies),
        detail=detail,
    )


def _p95(values: list[float]) -> Any:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    v = ordered[idx]
    return int(v) if isinstance(v, int) or float(v).is_integer() else round(float(v), 2)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(budgets: list[int], embedder_kind: str) -> dict[str, Any]:
    settings = Settings(embedder=embedder_kind)
    store, embedder, tokenizer = build_corpus(settings)

    corpus_tokens = sum(
        c.token_count for c in store.all_chunks(ORG_ID)[0]
    )
    questions = [*QUESTIONS, MEMORY_QUESTION]

    results: dict[str, Any] = {
        "meta": {
            "embedder": embedder.name,
            "documents": len(DOCUMENTS) + len(SUPERSEDED_DOCUMENTS),
            "chunks": len(store.all_chunks(ORG_ID)[0]),
            "corpus_tokens": corpus_tokens,
            "questions": len(questions),
            "memory_claims": len(SEED_CLAIMS),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "by_budget": {},
    }

    for budget in budgets:
        arms = [
            run_naive(store, embedder, tokenizer, questions, budget, "naive"),
            run_naive(store, embedder, tokenizer, questions, budget, "naive_postfilter"),
            run_naive(store, embedder, tokenizer, questions, budget, "naive_prefilter"),
            run_compiled(store, embedder, tokenizer, settings, questions, budget),
        ]
        results["by_budget"][str(budget)] = {a.name: asdict(a) for a in arms}

    store.close()
    return results


def format_table(results: dict[str, Any]) -> str:
    lines: list[str] = []
    meta = results["meta"]
    lines.append(
        f"corpus: {meta['documents']} docs / {meta['chunks']} chunks / "
        f"{meta['corpus_tokens']} tokens | {meta['questions']} questions | "
        f"{meta['memory_claims']} memory claims | embedder: {meta['embedder']}"
    )
    for budget, arms in results["by_budget"].items():
        lines.append("")
        lines.append(f"=== token budget: {budget} ===")
        header = (
            f"{'arm':<20} {'answer':>7} {'over':>6} {'tok':>7} {'dup':>7} "
            f"{'acl':>6} {'stale':>7} {'olddoc':>7} {'prov':>6} {'ms':>8}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for name, a in arms.items():
            lines.append(
                f"{name:<20} {a['answer_retention']*100:>6.1f}% "
                f"{a['budget_overrun_rate']*100:>5.0f}% "
                f"{a['mean_tokens']:>7.0f} "
                f"{a['duplicate_waste']*100:>6.1f}% "
                f"{a['acl_leak_rate']*100:>5.0f}% "
                f"{a['stale_fact_rate']*100:>6.0f}% "
                f"{a['outdated_doc_rate']*100:>6.0f}% "
                f"{a['provenance']*100:>5.0f}% "
                f"{a['mean_latency_ms']:>8.1f}"
            )
    lines.append("")
    lines.append(
        "answer=answer-bearing text retained | over=% prompts exceeding budget | "
        "tok=mean prompt tokens\ndup=duplicate token share | acl=% prompts leaking "
        "restricted content | stale=% carrying a superseded fact\nprov=% with a "
        "provenance manifest | ms=mean wall-clock"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Naive prompt vs compiled context benchmark")
    parser.add_argument("--budgets", default="800,1500,3000",
                        help="comma-separated token budgets")
    parser.add_argument("--embedder", default="hashing", choices=["hashing", "neural"])
    parser.add_argument("--json", dest="json_path", default=None,
                        help="write full results as JSON")
    args = parser.parse_args()

    budgets = [int(b) for b in args.budgets.split(",")]
    results = run(budgets, args.embedder)
    print(format_table(results))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nwrote {args.json_path}")


if __name__ == "__main__":
    main()
