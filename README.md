# Mnemos

**Context is a compiled artifact, not a concatenated string.**

Mnemos is a working RAG system built around one idea: the prompt you hand an LLM should
be *planned and budgeted*, not string-joined and truncated. It takes a question, a
governance policy and a hard token budget, and emits a **context bundle** — a
content-addressed prompt with a provenance manifest in which every included passage
records its source, its score, the operator that retrieved it, and the authorization
rule that admitted it.

It ships with a benchmark that measures the difference against a naive concatenated
prompt on the same corpus, same budget, same embedder.

```bash
git clone https://github.com/Harsha2803/mnemos && cd mnemos
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/mnemosctl serve        # → http://127.0.0.1:8000
.venv/bin/mnemosctl bench        # → the table below
```

No API key. No model download in the default path. Runs offline.

---

## The result

Same corpus (8 documents, 56 chunks, 8 memory claims), same 23 questions, same embedder,
same token budget. `mnemosctl bench --embedder neural`, budget 800:

| | naive concat | **compiled bundle** |
|---|---|---|
| Answer-bearing text retained | 100% | **100%** |
| Quoted a **superseded** policy revision | **100%** | **0%** |
| Carried a **superseded memory** fact | **61%** | **0%** |
| Leaked **restricted** content | 13% | **0%** |
| Duplicate token waste | 6.9% | **1.1%** |
| Has a provenance manifest | 0% | **100%** |
| Exceeded the token budget | 0% | 0% |
| Mean latency | 69 ms | 81 ms |

**The headline is the second row.** Every single naive prompt handed the model an
obsolete policy figure alongside the current one. Here is an actual naive prompt for
*"How many days of unused leave can I carry over?"*:

```
Carry-over of unused discretionary leave into the following calendar year is
capped at five working days.          ← Employee Handbook 2026  (current)

Carry-over of unused discretionary leave into the following calendar year is
capped at ten working days.           ← Employee Handbook 2024  (superseded)
```

Both retrieved. Both ranked highly — the obsolete text is often the *better* lexical
match. Nothing in the prompt marks which is current. The model will answer confidently
and has a coin-flip chance of being wrong, and no amount of reranking fixes it, because
this is not a relevance problem.

### Full results

<details open>
<summary><b>neural embedder</b> (<code>bge-small-en-v1.5</code>)</summary>

```
corpus: 8 docs / 56 chunks / 5387 tokens | 23 questions | 8 memory claims

=== token budget: 800 ===
arm                   answer   over     tok     dup    acl   stale  olddoc   prov       ms
naive                 100.0%     0%     800    6.9%    13%     61%    100%     0%     68.7
naive_postfilter      100.0%     0%     800    6.7%     0%     61%    100%     0%     68.1
naive_prefilter       100.0%     0%     800    6.7%     0%     61%    100%     0%     68.2
mnemos_compiled       100.0%     0%     770    1.1%     0%      0%      0%   100%     81.0

=== token budget: 1500 ===
naive                 100.0%     0%    1251   11.7%    22%     61%    100%     0%     57.9
mnemos_compiled       100.0%     0%    1456    5.9%     0%      0%      0%   100%     83.7

=== token budget: 3000 ===
naive                 100.0%     0%    1251   11.7%    22%     61%    100%     0%     56.7
mnemos_compiled       100.0%     0%    2887   14.0%     0%      0%      0%   100%     75.1
```
</details>

<details>
<summary><b>hashing embedder</b> (zero-download default — reproduces in seconds)</summary>

```
=== token budget: 800 ===
arm                   answer   over     tok     dup    acl   stale  olddoc   prov       ms
naive                  82.6%     0%     800   11.8%    43%     57%     74%     0%      8.5
naive_prefilter        82.6%     0%     800   11.2%     0%     57%     74%     0%      8.2
mnemos_compiled       100.0%     0%     771    1.8%     0%      0%      0%   100%     11.6

=== token budget: 1500 ===
naive_prefilter       100.0%     0%    1271   20.9%     0%     57%     96%     0%      5.3
mnemos_compiled       100.0%     0%    1455    7.2%     0%      0%      0%   100%     12.6
```

Under a weaker embedder the compiler also wins on **answer retention at a tight budget
(82.6% → 100%)**, because deduplicating overlapping chunks frees room for distinct
content.
</details>

### What this does *not* show

Stated plainly, because a benchmark that only reports its wins is marketing:

- **With a good embedder on this corpus, answer retention is a tie (100% vs 100%).**
  The corpus is 5.4k tokens; top-k almost always contains the answer, and the naive arm
  concatenates in score order so truncation only ever cuts distractor tails. The
  compiler's wins here are governance wins, not retrieval-quality wins.
- **The compiler is slower** — roughly 1.2–1.4×. It does strictly more work. The table
  is an argument about what that cost buys, not a claim of free lunch.
- **The corpus is synthetic.** It is built to have the properties real corpora have
  (repeated boilerplate, chunk overlap, superseded revisions, a restricted document),
  but it is not a public benchmark and these numbers are not comparable to one.
- **Duplicate waste rises at budget 3000** (14%) because more near-threshold content is
  admitted. Dedup is a similarity threshold, not a guarantee.

---

## How it works

Six phases, modelled on a query compiler:

```
ContextRequest
   │
   ├─ 1 BIND        intent + entity binding + authorization predicate
   ├─ 2 PLAN        logical operator DAG  (memory_scan · vector · lexical)
   ├─ 3 OPTIMISE    utility calibration → budget allocation w/ section floors
   ├─ 4 EXECUTE     deadline-bounded operators, degradation recorded not thrown
   ├─ 5 REFINE      RRF fusion → dedup → conflict resolution
   └─ 6 ASSEMBLE    trust fencing → canonical digest → manifest
   ▼
ContextBundle { digest, prompt, manifest, budget_report, explain }
```

### The three mechanisms that produce the numbers

**1. Authorization is pushed into the scan, never applied after ranking.**
Every retrievable item carries `(org, workspace, sensitivity, tags)`, and the
`AuthorizationPredicate` is evaluated *during* the scan. Post-filtering — the common
"we added auth" implementation, included in the benchmark as `naive_postfilter` — leaks
existence through result counts and silently drops recall when the nearest neighbours
happen to be inaccessible.

**2. Memory claims are bitemporal and never overwritten.**
Each claim carries *world time* (`valid_from`/`valid_to` — when the fact holds) and
*belief time* (`recorded_at`/`retracted_at` — when the system believed it). A write
arbitrates against conflicting claims inside the transaction, closes belief time on the
loser, and records a `supersedes` edge. Nothing is deleted, so `"what did this system
believe on 2025-06-01, about 2025-06-01?"` is an ordinary query — and a superseded fact
is structurally unreachable rather than merely down-ranked.

**3. The token budget is allocated, not truncated.**
Greedy on utility density with per-section floors and ceilings. Floors are why a
high-scoring document cannot evict the entire memory section — a failure that presents
as amnesia while retrieval "worked correctly". The assembled prompt is then *measured*
and re-allocated if it overshoots, with a final hard trim, so `tokens ≤ budget` is an
invariant rather than an estimate. A randomised test asserts it over 300 configurations.

### `EXPLAIN`

Every compilation is introspectable:

```bash
mnemosctl ask "How many days of unused leave can I carry over?" --explain
```

Actual output, abridged:

```json
{
  "authorization": {
    "rule_id": "rule:default-scope",
    "candidates_denied_by_acl": 6,
    "candidates_denied_by_currency": 26
  },
  "operator_actuals": [
    { "operator_id": "memory_scan_1",     "scanned":  7, "returned":  7,
      "denied_by_acl": 0, "denied_by_currency":  0, "latency_ms": 1.603 },
    { "operator_id": "vector_search_1",   "scanned": 56, "returned": 32,
      "denied_by_acl": 3, "denied_by_currency": 13, "latency_ms": 3.274 },
    { "operator_id": "lexical_search_1",  "scanned": 56, "returned": 32,
      "denied_by_acl": 3, "denied_by_currency": 13, "latency_ms": 3.790 }
  ],
  "refine": { "fused": 43, "dedup_removed": 7, "dedup_tokens_saved": 826,
              "conflicts_resolved": 1 },
  "allocator": { "strategy": "greedy_density_with_section_floors",
                 "admitted": 12, "evicted": 23, "binding_constraint": "tokens" },
  "budget_fit": { "passes": 2, "assembly_overhead_tokens": 195,
                  "prompt_tokens": 771, "budget": 800, "within_budget": true }
}
```

Reading that top to bottom: 6 candidates were refused by authorization and **26 by
document currency** — that is the obsolete-handbook content being excluded before it can
be ranked. Dedup then recovered **826 tokens** of repeated boilerplate, one memory
conflict was arbitrated, and the allocator admitted 12 of 35 candidates before running
out of tokens.

`binding_constraint` names the resource that actually ran out. That single field turns
"the answer was bad" into "you were token-bound — raise the budget."

---

## The localhost inspector

```bash
mnemosctl serve --embedder neural     # or omit for the zero-download default
```

Side-by-side naive vs compiled for any question, with obsolete / restricted / superseded
content highlighted in red in both prompts, the full provenance manifest, and the
`EXPLAIN` tree.

| Endpoint | Purpose |
|---|---|
| `GET /` | The inspector UI |
| `POST /v1/compare` | Both arms + metrics for one question |
| `POST /v1/context:compile` | Compile a bundle |
| `GET /v1/memory` | All claims, including retracted, with belief state |
| `POST /v1/memory` | Write a claim — response reports what it superseded |
| `GET /readyz` | Corpus and embedder status |

---

## Design decisions worth defending

| Decision | Why |
|---|---|
| Utility is calibrated from rank, not taken from the fused score | RRF scores span ~0.0143–0.0164. Feeding that into `utility/tokens` makes the numerator constant, so the allocator buys the *shortest* passages — headings and boilerplate. This was a real bug found by the benchmark; there is a regression test pinning the dynamic range. |
| Exclusivity applies to semantic/profile/procedural, **not** episodic | Two claims that "region is EU" and "region is US" cannot both hold. Two episodic memories at the same instant are normal — a person can do two things at once. Constraining them would fabricate conflicts. |
| Budget is verified against the assembled prompt, not estimated | Section headers, trust fences and citation labels are real tokens. Estimating them makes the guarantee approximate, and an approximate guarantee is not one. |
| Conflict losers are demoted, not dropped | Silently discarding a contradiction is how a system becomes confidently wrong. |
| Default embedder needs no download | The benchmark must reproduce on any machine in seconds. The neural adapter implements the identical port and is one flag away. |
| SQLite, not Postgres | Single-node, zero-setup, and the bitemporal logic is identical. The scaling story is in `docs/`, and it is labelled as design intent, not as something exercised. |

---

## Layout

```
src/mnemos/
  core.py        ids · clock · tokenizer · canonical digest · trust tiers · ACL predicate
  embed.py       Embedder port + hashing (default) and sentence-transformers adapters
  store.py       SQLite: bitemporal claims, supersession edges, chunks, doc currency
  retrieval.py   operators w/ ACL pushdown · RRF · utility calibration · dedup · conflicts
  compiler.py    ▲ the six phases, the allocator, EXPLAIN ▲
  baseline.py    the control arm — three naive variants
  ingest.py      PDF/text extraction + structure-aware chunking with char offsets
  dataset.py     the evaluation corpus and gold labels
  bench.py       the metrics harness
  app.py         FastAPI + the inspector UI
  cli.py         mnemosctl
tests/           23 tests, each guarding a claim made above
docs/            architecture, ADRs, threat model, roadmap
```

Run the suite:

```bash
.venv/bin/python -m pytest -q       # 23 passed
```

---

## Relationship to `docs/`

`docs/` describes the full target architecture — Postgres + pgvector, Neo4j, an agent
runtime, an MCP tool service, a knowledge graph. **This repository implements the
kernel and the RAG flow of that design**, on SQLite and numpy, as a single-node system.

The documents are honest about the gap: scaling stages beyond single-node are labelled
as design intent rather than as anything measured. See
[`TRACKER.md`](TRACKER.md) for exactly what is built versus planned.

## License

Apache-2.0 — see [ADR-0012](docs/ArchitectureDecisionRecords/ADR-0012-licensing-and-openness.md).
