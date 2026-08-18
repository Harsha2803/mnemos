# Mnemos

**An enterprise AI assistant — chat over your documents (RAG), your database (NL2SQL) and
your tools (MCP). Multi-tenant, authenticated, and inspectable.**

One conversation surface. Today, ask it something and a router selects plain chat, your
documents, or your database, then shows which flow answered and why. The committed finish
adds one safely approved MCP call, governed/inspectable context, and a reproducible portfolio
release. Underneath it is per-tenant row-level security and real OIDC; broader agent and SaaS
product features are deliberately deferred rather than implied to be coming next.

Everything is free and self-hosted: Postgres + pgvector, Redis, MinIO, Keycloak and Ollama
in containers. No API key is required for any capability.

It carries **one deep technical claim, and it is measured rather than asserted**: the
prompt handed to the model is a *compiled, budgeted artifact you can open*, not a
concatenated string. [The numbers are below.](#the-deep-technical-claim-context-is-a-compiled-artifact)

---

## What is actually built today

The gap between optional architecture seams and what runs is stated here rather than left
for you to discover. This is the honest status.

**Built and running:**

| | |
|---|---|
| **The stack** | Nine containers — postgres (pgvector), redis, minio, keycloak, ollama, api, worker, realtime, web — plus a one-shot `migrate` that runs `alembic upgrade head` and must exit successfully before the API starts. Healthchecks on the seven that serve a port |
| **The schema** | 41 tables across identity, memory, knowledge, chat, context, datasources, tools, prompts and observability. **40 with `FORCE` row-level security**, enforced against an unprivileged app role and proven by a test against a real Postgres — not merely declared in the catalogue |
| **Identity** | Full OIDC round trip against Keycloak (PKCE S256, split-horizon issuers), internal password auth behind the same provider seam, platform JWT with refresh-token rotation and family revocation, and `mnemosctl bootstrap` to create the first org and admin |
| **CI** | Every PR runs pytest against a real Postgres and a real Keycloak, ruff, `mypy --strict`, `alembic check`, and a frontend gate of lint + `tsc` + tests + a real `next build` |
| **The app shell** | A themed, accessible three-column Next.js app at `http://localhost:3000`, with a generated API client and one real call end to end |
| **Sign-in** | A sign-in screen over the OIDC round trip, sessions that survive a reload, real sign-out, and a fail-closed route guard — a route that declares nothing is authenticated |
| **Chat** | An Ollama-backed gateway behind a `ChatModel` port, persisted sessions and messages, and SSE streaming that renders token by token |
| **RAG** | Upload → extract → chunk → embed onto pgvector HNSW → hybrid retrieval (vector + trigram, RRF-fused, deduplicated) → an answer with citations you click into. **Authorization is a predicate inside the scan and superseded revisions are excluded there too**, both pinned by tests rather than asserted |
| **NL2SQL** | Schema introspection + business glossary → Ollama SQL generation → AST read-only allowlist → execution as `mnemos_ro` → narration and a visible SQL/result/denial panel. The parser guard and database role are independent defences |
| **Automatic routing** | A deterministic, local-first classifier selects chat, RAG, or NL2SQL for every message. The stream and persisted assistant turn carry a compact reason shown beside the answer; there is no manual mode selector |
| **Source ingestion** | MinIO/S3, local-filesystem, and curated-HTTP connectors feed durable Redis Streams jobs. Workers heartbeat, retry with backoff, surface stuck leases, and publish per-job progress/history to the Sources screen |

**Committed but not built yet.** Stated plainly, because a README that lets you assume
otherwise is lying by omission:

- **There is no tool runtime yet.** `B3` adds one self-hosted MCP call with per-user
  credentials, trust-tier authorization, durable approval, and invocation history.
- **The context inspector shows a cited passage, not a compiled context bundle.** The
  compiler, the budget allocator and the bitemporal memory layer that produced the numbers
  below are still quarantined in `backend/src/mnemos/_v1/` on SQLite. Retrieval has been
  ported onto Postgres; memory and the compiler have not, which is why the benchmark below
  is still labelled as measured on SQLite.

**Deliberately deferred:** multi-step agent loops (`B4`), API keys/full RBAC/tag ACL UI
(`C1`), prompt and cost management (`C2`), and conversation-product depth (`C3`). Their
schema or architectural seams may remain, but they are not promises in the portfolio plan.

**Phase A's product surface is complete** — sign-in, chat, documents, database, and router.
The complete remaining finish is **`B3` → `C4` → reduced `D1`**. The milestone plan is
[`TRACKER.md`](TRACKER.md) §3.0 and the
architecture is [`docs/ADAPTATION.md`](docs/ADAPTATION.md); `TRACKER.md` §3 is the
authoritative list of what is built, with the evidence for each claim.

---

## Quickstart

```bash
git clone https://github.com/Harsha2803/mnemos && cd mnemos
docker compose up -d                    # nine services, web included
docker compose exec api mnemosctl bootstrap \
    --org-slug mnemos --org-name Mnemos --admin-email admin@mnemos.local
```

`bootstrap` reads the admin password from `MNEMOS_BOOTSTRAP_ADMIN_PASSWORD` or prompts for
it — never from an argument, because `argv` is world-readable through `/proc` and lands in
shell history. It is idempotent: a second run creates whatever is missing and changes
nothing that exists.

| | Where |
|---|---|
| The app | `http://localhost:3000` |
| API + Swagger | `http://localhost:8000` · `http://localhost:8000/docs` |
| Keycloak | `http://localhost:8080` (`admin`/`admin`) |
| MinIO console | `http://localhost:9001` (`mnemos`/`mnemos-dev-secret`) |
| Postgres · Redis | `localhost:15432` · `localhost:6380` — shifted off the default ports so they do not clash with a host installation |

Check it came up:

```bash
curl http://localhost:8000/readyz             # postgres, redis, ollama, objectstore → ok
docker compose exec api mnemosctl db doctor   # 41 tables, 40 with FORCE row-level security
```

Those credentials are dev-stack credentials in the same class as Keycloak's `admin`/`admin`.
They are never to be reused anywhere real.

---

## The deep technical claim: context is a compiled artifact

The prompt you hand an LLM should be *planned and budgeted*, not string-joined and
truncated. Mnemos takes a question, a governance policy and a hard token budget, and emits
a **context bundle** — a content-addressed prompt with a provenance manifest in which every
included passage records its source, its score, the operator that retrieved it, and the
authorization rule that admitted it.

It ships with a benchmark measuring the difference against a naive concatenated prompt on
the same corpus, same budget, same embedder.

> ### These numbers were measured on the v0.1 SQLite kernel
>
> They come from `backend/src/mnemos/_v1/`, which runs on SQLite and numpy and is
> quarantined from the new stack. **The kernel finishes its port to Postgres + pgvector in
> milestone `C4`, and the benchmark must be re-run and these numbers replaced at that
> point** — see [TRACKER §1](TRACKER.md#1-what-this-is-30-seconds). Until then they are
> honest about what they measured and silent about the system as it now stands.
>
> Reproduce the zero-download arm in seconds:
>
> ```bash
> python3 -m venv .venv && .venv/bin/pip install -e "./backend[dev]"
> .venv/bin/python -m mnemos._v1.cli bench --budgets 800,1500,3000
> ```

Same corpus (8 documents, 56 chunks, 8 memory claims), same 23 questions, same embedder,
same token budget. `bench --embedder neural`, budget 800:

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
- **There is no LLM in the loop.** The benchmark measures *what reaches the model*, not
  answer correctness. That arm becomes possible once the gateway lands in `A1`, and it
  must not replace the deterministic metrics.

---

## How the compiler works

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
invariant rather than an estimate. A randomised test asserts it over 300 configurations,
and the new schema backs it with a CHECK constraint on `context_bundle`.

### `EXPLAIN`

Every compilation is introspectable:

```bash
.venv/bin/python -m mnemos._v1.cli ask "How many days of unused leave can I carry over?" --explain
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

**This is what becomes the context inspector in `C4`**, as a panel in the app rather than
a JSON dump: open any answer and see what was admitted, what was excluded and why, and
the token spend against budget.

### The v0.1 inspector

Until `C4` lands, the compiler has its own standalone UI, served from the quarantined
kernel and unconnected to the container stack:

```bash
.venv/bin/python -m mnemos._v1.cli serve      # → http://127.0.0.1:8000
```

Side-by-side naive vs compiled for any question, with obsolete / restricted / superseded
content highlighted in red in both prompts, the full provenance manifest, and the
`EXPLAIN` tree. Note that it binds port 8000, which the containerised `api` also uses —
run one or the other.

---

## Design decisions worth defending

| Decision | Why |
|---|---|
| Utility is calibrated from rank, not taken from the fused score | RRF scores span ~0.0143–0.0164. Feeding that into `utility/tokens` makes the numerator constant, so the allocator buys the *shortest* passages — headings and boilerplate. This was a real bug found by the benchmark; there is a regression test pinning the dynamic range. |
| Exclusivity applies to semantic/profile/procedural, **not** episodic | Two claims that "region is EU" and "region is US" cannot both hold. Two episodic memories at the same instant are normal — a person can do two things at once. Constraining them would fabricate conflicts. |
| Budget is verified against the assembled prompt, not estimated | Section headers, trust fences and citation labels are real tokens. Estimating them makes the guarantee approximate, and an approximate guarantee is not one. |
| Conflict losers are demoted, not dropped | Silently discarding a contradiction is how a system becomes confidently wrong. |
| Default embedder needs no download | The benchmark must reproduce on any machine in seconds. The neural adapter implements the identical port and is one flag away. |
| The v0.1 kernel was SQLite; the platform is Postgres + pgvector | SQLite was the right call for a single-node kernel with zero setup, and the bitemporal logic is identical either way. The platform needs what SQLite cannot give: real row-level security, real exclusion constraints and real migrations. That is why the kernel is a *port* (`A2` and `C4`) rather than a rewrite. |
| NL2SQL targets a separate database with a read-only role | The AST guard becomes the second line of defence rather than the only one. A guard that is the only defence is one parser bug away from a write. |
| Zero paid dependencies in the default path | The benchmark must reproduce on any machine, and a portfolio piece that needs somebody's API key is a portfolio piece nobody runs. |

---

## Layout

```
backend/src/mnemos/
  core/           config · errors · logging · security · ids · clock · shared enums
  platform/       async engine + tenant-scoped session · redis · models registry
  features/       identity · memory · retrieval · context · knowledge · connectors
                  datasources · chat · tools · prompts · observability
  flows/          rag · nl2sql · agent · router
  entrypoints/    api (FastAPI) · worker · realtime (WS) · cli.py (mnemosctl)
  migrations/     alembic, one logical change per revision, reversible
  _v1/            ▲ the v0.1 kernel — compiler, memory, benchmark, on SQLite ▲
                    retrieval ported out in A2; memory + compiler remain, ported in C4
backend/tests/    the suite — identity, tenant isolation, tokens, invariants
frontend/src/     Next.js app router · components · generated API client
deploy/           postgres init (extensions + analytics warehouse) · keycloak realm
docs/             architecture, design system, threat model, 12 ADRs
bench_results/    the JSON behind the tables above
```

Run the gates the way CI does:

```bash
cd backend  && ../.venv/bin/python -m pytest      # 278 passed (needs Docker + Keycloak)
cd frontend && npm ci && npm run lint && npx tsc --noEmit && npm run test && npm run build
```

---

## Relationship to `docs/`

`docs/` (Architecture, SystemDesign, DatabaseDesign, APIContract, ThreatModel, DesignSystem
and 12 ADRs) preserves both the committed design and optional extension seams. The
resume-focused finish is narrower: `B3`, `C4`, and reduced `D1`.

The distinction is deliberate and stated rather than hidden: deferred product features and
scaling stages beyond single-node are design options, not unfulfilled claims. See
[`TRACKER.md`](TRACKER.md) §3 for exactly what is built, with evidence, and §3.0 for the
three-milestone finish.

## License

Apache-2.0 — see [ADR-0012](docs/ArchitectureDecisionRecords/ADR-0012-licensing-and-openness.md).
