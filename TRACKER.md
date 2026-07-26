# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It states what is built, the constraints
> you must not violate, and the exact next task. When you finish work, update this file
> *in the same commit* — a stale tracker is worse than none.

**Last updated:** 2026-07-26
**Phase:** M1 — rebuilding as a containerized AI workspace chatbot.
**Next task:** `M1` remaining items (see §5)

---

## 0. Agent operating instructions

1. **Read in this order:** this file → `README.md` → the module you are changing →
   [`docs/CodingStandards.md`](docs/CodingStandards.md).
2. **Do not re-litigate decisions in §2.** They are settled and several are load-bearing
   for numbers published in the README. If you believe one is wrong, write an ADR
   superseding it — do not silently deviate.
3. **Every change ends with:** `pytest` green + benchmark re-run + README numbers updated
   if they moved + this tracker updated + a conventional commit.
4. **If you change anything in the retrieval or compile path, re-run the benchmark and
   paste the new numbers into the README.** The README publishes measured results; a
   change that moves them and does not update them makes the repository dishonest.
5. **No placeholders, no `TODO`, no stubbed returns.** Split a task rather than stub it.

---

## 0.1 SCOPE CHANGE — read this before anything else

The project was reframed on 2026-07-26. v0.1 was a **benchmark harness with a prompt-diff
viewer** — an engine and a lab bench, not a product. That was a misread of the goal.

**What is actually wanted:** a **chatbot** that does many things — RAG over documents,
NL2SQL over a database, MCP tools, auth, ingestion from cloud sources — where governed
memory and compiled context are the feature that *stands out among* those, not the whole
app.

The full plan, the JIVA capability map, the schema and milestones M1–M14 now live in
**[`docs/ADAPTATION.md`](docs/ADAPTATION.md)**. Read that next.

The v0.1 kernel is preserved in `backend/src/mnemos/_v1/` and is ported (not rewritten)
in milestone M4.

## 1. What this is (30 seconds)

**Mnemos — context is a compiled artifact, not a concatenated string.**

A working RAG system whose prompt is *planned and budgeted* rather than string-joined and
truncated. Ships with a benchmark measuring it against a naive concatenated prompt on the
same corpus, budget and embedder.

**Headline measured result** (neural embedder, 800-token budget, 23 questions):
naive quoted a **superseded policy revision in 100% of prompts**; compiled, **0%**.
Superseded memory facts: 61% → 0%. Restricted-content leak: 13% → 0%. Duplicate token
waste: 6.9% → 1.1%. Answer retention: 100% both. Latency: 69 ms → 81 ms.

---

## 2. Non-negotiable constraints

| # | Constraint | Why |
|---|---|---|
| C1 | **Zero paid dependencies in the default path.** No API key for any capability. | The benchmark must reproduce on any machine |
| C2 | **Default embedder needs no download.** Neural is opt-in via the same port. | Same |
| C3 | **`tokens_consumed <= budget` is an invariant, not an estimate.** | It is a published claim; `test_compiled_prompt_never_exceeds_budget` + a 300-case randomised test guard it |
| C4 | **Authorization is evaluated inside the scan. Post-filtering is banned.** | Published claim; `test_acl_pushdown_beats_post_filtering_on_yield` |
| C5 | **Memory is never overwritten.** Writes supersede and close belief time. | Published claim; the staleness metric depends on it |
| C6 | **Superseded document revisions are excluded in the scan, not down-ranked.** | The headline number. Obsolete text often out-ranks current text |
| C7 | **Utility must be calibrated from rank before allocation.** | Raw RRF scores are nearly flat; skipping this makes the allocator buy boilerplate. Regression test pins the dynamic range |
| C8 | **Conflict losers are demoted and recorded, never silently dropped.** | |
| C9 | **Never use the work email/account** (`@jktech.com`, `harshaJKT`). Personal only. | |
| C10 | **The baseline must stay a fair representative**, not a strawman. `test_naive_arm_does_include_superseded_revisions` guards this. | A rigged baseline invalidates everything |

---

## 3. Current state — what is actually built

### ✅ Working and tested (23 tests passing)

| Module | What it does |
|---|---|
| `core.py` | ids, `Clock`/`IdGenerator` ports, heuristic tokenizer, canonical digest, trust tiers, `AuthorizationPredicate`, settings |
| `embed.py` | `Embedder` port; hashing adapter (default, no download) + sentence-transformers adapter |
| `store.py` | SQLite. Bitemporal claims (world time × belief time), supersession edges, in-transaction arbitration, chunks, document currency |
| `retrieval.py` | vector / lexical / memory operators with ACL **and** currency pushdown, RRF fusion, utility calibration, dedup, conflict resolution |
| `compiler.py` | six phases, greedy-density allocator with section floors/ceilings, measured budget fit + hard trim, trust fencing, manifest, `EXPLAIN` |
| `baseline.py` | three naive variants (no ACL / post-filter / pre-filter) |
| `ingest.py` | PDF + text, structure-aware chunking with char offsets |
| `dataset.py` | 8-document corpus, 23 gold-labelled questions, 8 memory claims, 2 superseded revisions, 1 restricted doc, 1 injection doc |
| `bench.py` | 7-metric harness |
| `app.py` | FastAPI + self-contained inspector UI |
| `cli.py` | `mnemosctl serve \| bench \| ask` |

### ⬜ Designed in `docs/` but NOT built

Postgres + pgvector · Neo4j knowledge graph · agent runtime · MCP tool service · NL2SQL
flow · OIDC/SAML auth · transactional outbox · Celery workers · Next.js dashboard.

`docs/` describes the full target architecture. This repo implements its **kernel and RAG
flow** on SQLite + numpy. The gap is stated in the README and is not a defect.

### Environment

| Fact | Value |
|---|---|
| Repo | `/home/shreeharsha/Personal/Projects/Resume_001/mnemos` |
| Python | 3.12.3, venv at `.venv` |
| Install | `.venv/bin/pip install -e .` (add `[neural]` for bge-small) |
| Serve | `.venv/bin/mnemosctl serve` → `http://127.0.0.1:8000` |
| Bench | `.venv/bin/mnemosctl bench --embedder neural` |
| Tests | `.venv/bin/python -m pytest -q` → 23 passed |
| Git identity | `Cheella Sree Harsha <cheellasreeharsha2803@gmail.com>` (repo-local) |
| GitHub | `Harsha2803`, repo private |

---

## 4. Known gaps and honest weaknesses

Recorded so they are not rediscovered as surprises:

1. **Answer retention is a tie under a good embedder** (100% vs 100%). The corpus is
   5.4k tokens — too small for budget pressure to bite. Growing the corpus 10× is the
   single highest-value change to make the retention claim meaningful. → task `N1`
2. **Duplicate waste rises at large budgets** (14% at 3000) because more
   near-threshold content is admitted. Dedup is a threshold, not a guarantee.
3. **Brute-force cosine over all chunks** on every query. Fine at 56 chunks, `O(n)` and
   wrong at 100k. The `Embedder`/store split makes an ANN index a contained change.
4. **`all_chunks()` reloads the whole corpus per operator call** — three times per
   compile. Obvious caching win, deliberately not done yet.
5. **No LLM in the loop.** The benchmark measures *what reaches the model*, not answer
   correctness. That is a deliberate scope choice (no paid API, no judge), and it is
   stated in the README.
6. **The heuristic tokenizer approximates BPE.** Within a few percent on English prose;
   a `tiktoken` adapter would remove the approximation.

---

## 5. NEXT TASK

### `N1` — Grow the corpus until budget pressure is real

**Why this first.** It is the only change that can move the headline retention number
from "tie" to a measured win, and it makes every other metric more credible.

**Deliverables**
1. Expand `dataset.py` to ~50k+ corpus tokens — more documents, more near-miss
   distractors on the same topics, more superseded revisions. Keep it deterministic.
2. Add ~40 more gold-labelled questions. Every `answer_key` must be verifiable as
   present exactly once (there is a diagnostic pattern for this in the git history —
   an earlier labelling bug silently capped retention at 13/23 for both arms).
3. Re-run both embedders across budgets 400/800/1500/3000.
4. **Update the README table with whatever comes out**, including if the compiler loses.

**Acceptance**
- `pytest` green.
- Corpus tokens ≥ 50,000; questions ≥ 60; every answer key reachable.
- README numbers regenerated and matching `bench_results/*.json`.

**Commit:** `feat(dataset): scale evaluation corpus to create real budget pressure`

### Then, in order
- `N2` — cache `all_chunks()` per compile; measure the latency delta (gap 3/4 above).
- `N3` — `tiktoken` adapter behind the `Tokenizer` port; re-run and report any drift.
- `N4` — persist bundles to SQLite; add `GET /v1/context/bundles/{digest}` and `:replay`.
- `N5` — golden-bundle fixtures in CI so a context regression fails the build.
- `N6` — GitHub Actions: ruff + mypy + pytest + benchmark smoke run.

---

## 6. Blockers

*None.*

---

## 7. Update protocol

When you finish a task, in the **same commit**:

1. Move it from §5 to §3, or add it to §4 if it revealed a new weakness.
2. Rewrite §5 to fully specify the next task at the same level of detail — the next
   agent may have no context beyond this file.
3. Update the header (`Last updated`, `Phase`, `Next task`).
4. If benchmark numbers moved, update the README **and** `bench_results/*.json`.
5. If you deviated from a documented design, say so explicitly in §4. An undocumented
   deviation is the most expensive thing to discover later, because the docs will be
   trusted and will be wrong.
