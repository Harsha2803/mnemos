# Roadmap

Strategy and sequencing. Task-level detail lives in
[ImplementationPlan.md](ImplementationPlan.md); live status lives in
[`TRACKER.md`](../TRACKER.md).

---

## 1. Release strategy

| Release | Contents | Repo state | Purpose |
|---|---|---|---|
| **v0.1 — Kernel** | M0–M5 | Private | The thesis, provable. Context compiler + `EXPLAIN` + bitemporal memory. |
| **v0.2 — First flow** | + M6 (RAG) | **Go public here** | An abstraction with a working consumer. |
| **v0.3 — Grounding** | + M7, M8 | Public | Graph retrieval + NL2SQL. Two more consumers prove the kernel generalizes. |
| **v0.4 — Agency** | + M9, M10 | Public | Agent runtime + MCP as a separate service. |
| **v0.5 — Legible** | + M11 | Public | Dashboard. The screenshots that make the README land. |
| **v1.0 — Hardened** | + M12 | Public | Measured, chaos-tested, documented. |

**Go public at v0.2, not v0.1 and not v1.0.** At v0.1 the repository is a compiler with
no consumer — impressive to read, hard to evaluate. At v1.0 you have spent seven months
building in private with nothing to show. v0.2 is the first point where a stranger can
clone, run `make up`, ask a question about a PDF, and see `EXPLAIN` account for every
token. That is the moment the work becomes legible to someone who did not write it.

## 2. Scope discipline

The failure mode for a project this size is not writing bad code — it is writing too
much mediocre code. Three rules:

**One thesis.** Everything answers "context is a compiled artifact." A feature that
doesn't strengthen that claim is a distraction regardless of how interesting it is.

**Depth over breadth in the novel parts, breadth over depth in the conventional parts.**
The compiler and the memory substrate get exhaustive tests, property-based invariants,
and `EXPLAIN`-grade introspection. Auth and the gateway get a competent, well-tested
implementation and nothing more — they are solved problems and prior production work
already demonstrates them.

**Cut features, never rigor.** A missing feature reads as scope discipline. Missing
tests, absent types, or a silent failure path reads as an engineer who does not know the
difference — which is precisely the impression the project exists to prevent.

## 3. What gets cut first if time runs short

In order:

1. **M11 dashboard** — replaceable by a README with real `EXPLAIN` output and a terminal
   recording. Expensive to build, cheap to substitute.
2. **M10 MCP generation from OpenAPI** (M10-T10) — the remote client and the
   Mnemos-as-MCP-server are the parts that matter; the generator is a nice-to-have.
3. **M7 knowledge graph** — the compiler's operator algebra already supports a graph
   operator; a documented, un-implemented operator is an acceptable gap if the other four
   are real.
4. **M9 reflection/critic sophistication** — a two-state agent that checkpoints and
   replays correctly beats a five-state agent that does neither.

**Never cut:** the exclusion constraint (M3-T3), ACL pushdown (M4-T4), the recall test
(M4-T12), the budget allocator (M5-T8), `EXPLAIN` (M5-T15), golden bundles (M5-T18), the
SQL AST guard (M8-T5), or trust-tier re-authorization (M10-T8). Each of those is either
the thesis itself or a security property that cannot be bolted on afterwards.

## 4. Explicit non-goals

| Non-goal | Why |
|---|---|
| Multi-cloud storage/messaging abstraction | Already proven in prior professional work. Rebuilding it demonstrates nothing new. |
| Kubernetes, Helm, Terraform | Deployment detail. Compose proves the architecture at zero cost. |
| Model training, fine-tuning, or an eval harness | Different problem domain; would double the scope. |
| A chat product | The dashboard is an inspector. The moment it becomes a chat UI, the project reads as another chatbot. |
| Any paid dependency in the default path | Hard constraint. |
| Cloud warehouse connectors | Cannot be honestly exercised without paying. The `SqlDialect` port keeps them a configuration exercise. |
| Benchmark-chasing on public RAG leaderboards | The claim is about *governed, explainable, budgeted* context — not top-line retrieval accuracy. Optimizing for a leaderboard would distort the design. |

## 5. Open questions

Recorded now, decided when there is evidence rather than opinion. Each becomes an ADR.

| # | Question | Decide by | Current lean |
|---|---|---|---|
| Q1 | Does the utility model learn usefully from feedback, or is a static prior good enough? | M5 + 2 weeks of data | Static prior first; EWMA only if measurably better |
| Q2 | Is Postgres FTS sufficient, or is real BM25 (`pg_search`) needed? | M6 | FTS until a measured recall gap appears |
| Q3 | Should working memory move fully into Redis Streams, or stay Postgres-primary? | M9 | Redis-primary with Postgres durability on session close |
| Q4 | Does semantic caching of bundles cause stale-authorization risk? | M12 | Exact-match only unless proven safe |
| Q5 | Is a 3B local model adequate for NL2SQL generation, or does the flow need 7B+? | M8 | Measure; the flow may need a larger tier declared as a requirement |
| Q6 | Should the audit log be hash-chained? | v1.0 | Append-only grants are sufficient at this scope |

**Q5 is the one most likely to force a real decision.** If a 3B model cannot generate
correct SQL for non-trivial schemas, the honest response is to declare a minimum model
tier for that flow — not to quietly hardcode a hosted fallback and break the zero-cost
guarantee.

## 6. Success criteria

The project succeeds if a senior engineer at an AI infrastructure company can clone it,
run it in under ten minutes with no API key, and reach these conclusions:

1. This person designs systems, not features.
2. The central idea — context as a compiled artifact with `EXPLAIN` — is genuinely
   original and correctly executed.
3. The security model is thought through at a level most projects never reach.
4. The tests would catch a regression in the parts that matter.
5. The documentation would let them contribute without asking a question.

Stars, forks, and traffic are not success criteria. One good conversation in one
interview is.
