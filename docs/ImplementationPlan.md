# Implementation Plan

**Task IDs are stable and referenced by [`TRACKER.md`](../TRACKER.md).** Never renumber
them; append instead.

**Sequencing rule:** every milestone ends with something demonstrable. No milestone
produces only scaffolding, because a milestone you cannot demo is a milestone you cannot
verify.

**The thesis milestone is M5.** M0–M5 is the vertical slice that proves the project's
central claim. If time runs short, M0–M5 plus M6 is a complete and defensible artifact;
M7 onward broadens it.

---

## Milestone map

```
M0 Foundations ──▶ M1 Identity ──▶ M2 Inference ──▶ M3 Memory ──▶ M4 Retrieval
                                                                       │
                                                                       ▼
                                                        ┌──── M5 CONTEXT COMPILER ◀── the thesis
                                                        │
          ┌─────────────────┬─────────────────┬─────────┴────────┐
          ▼                 ▼                 ▼                  ▼
      M6 Flow A         M7 Graph          M8 Flow B          M9 Agent
        (RAG)                              (NL2SQL)          runtime
                                                                  │
                                                                  ▼
                                                          M10 Flow C (MCP)
                                                                  │
                                            M11 Dashboard ◀───────┘
                                                  │
                                                  ▼
                                          M12 Hardening
```

---

## M0 — Foundations

**Goal:** a running, observable, empty system with CI that enforces the architecture.

| ID | Task | Deliverable |
|---|---|---|
| M0-T1 | `pyproject.toml`, src-layout, Ruff/mypy strict, pre-commit | Toolchain green on an empty package |
| M0-T2 | `core/config.py` — Pydantic `BaseSettings`, fail-fast validation, `ModelTier` enum | `.env.example` + startup validation |
| M0-T3 | `core/errors.py` — exception hierarchy + RFC 9457 mapping | Problem Details on every error path |
| M0-T4 | `core/{ids,clock,canonical,result,pagination}.py` | UUIDv7, `Clock` port, canonical JSON + sha256, `Result[T,E]`, signed cursors |
| M0-T5 | `core/telemetry.py` — OTel + structlog, contextvar binding | `trace_id == request_id` on every log line |
| M0-T6 | `core/di.py` — container, provider registry, composition root | One module names concrete adapters |
| M0-T7 | `platform/db` — async engine, session, `UnitOfWork`, RLS GUC binding | Transaction boundaries in the app layer |
| M0-T8 | Alembic setup + `0001_initial_extensions` (`pgvector`, `pg_trgm`, `btree_gist`, `citext`) | Reversible migration |
| M0-T9 | `deploy/compose` — postgres, redis, neo4j, rabbitmq, minio, ollama, langfuse, otel-collector | `make up` brings up the full stack |
| M0-T10 | FastAPI app skeleton: correlation-ID middleware, `/healthz`, `/readyz`, OpenAPI | `readyz` checks deps, `healthz` does not |
| M0-T11 | `.importlinter` contracts 1–5 | CI fails on a boundary violation |
| M0-T12 | GitHub Actions: lint, types, import-linter, unit, integration (testcontainers), bandit, pip-audit, gitleaks | All gates green |
| M0-T13 | `Makefile`: `up down logs migrate test lint fmt seed calibrate` | One-command workflows |

**Exit criteria**
- `make up && make migrate && make test` succeeds from a clean clone.
- A deliberate `from sqlalchemy import ...` in a `domain/` module **fails CI**.
- `/readyz` returns 503 when Postgres is stopped and 200 when it returns.

---

## M1 — Identity, tenancy, and the policy decision point

**Goal:** nothing in the system is reachable without an authenticated principal and an
explicit allow.

| ID | Task | Deliverable |
|---|---|---|
| M1-T1 | Migration: `org`, `workspace`, `app_user`, `session`, `api_key` | Schema per DatabaseDesign §3 |
| M1-T2 | Migration: `role`, `role_permission`, `role_binding` with `is_protected` | Federated escalation guard |
| M1-T3 | Enable RLS + `FORCE` on all tenant tables; `app.current_org` GUC set by UoW | Cross-tenant reads return zero rows |
| M1-T4 | Password auth: Argon2id, `POST /v1/auth/token` | Access 15 min + refresh rotation with reuse detection |
| M1-T5 | API-key auth: split `key_id.secret`, indexed lookup, live revocation check | Revocation effective immediately |
| M1-T6 | JWT issue/verify: EdDSA, algorithm allow-list, explicit `iss`/`aud`/`exp` | Never reads `alg` from the token |
| M1-T7 | OIDC provider framework: Strategy + factory, DB-stored provider config, JWKS (RSA+EC) | Adding an IdP = a DB row |
| M1-T8 | Attribute mapping engine: dot-notation nested claims, ordered fallbacks, JIT provisioning | Azure AD / Keycloak / generic |
| M1-T9 | `PolicyDecisionPoint` port + compiled policy AST, Redis-cached, deny-by-default | Returns a `rule_id` with every decision |
| M1-T10 | Auth middleware → `Principal` in request state + structlog binding | Full request attribution |
| M1-T11 | `audit_log` (partitioned) + append-only grants; denials logged at allow-fidelity | Tamper-resistant by grant |
| M1-T12 | Tests: RLS isolation, revocation, protected-role guard, `404`-not-`403` | Security tests, not happy-path |

**Exit criteria**
- Org A cannot read org B's rows even through a deliberately unfiltered query.
- An external IdP asserting an admin role does **not** produce an admin.
- A revoked API key fails on the very next request.

---

## M2 — Inference gateway (local-first)

**Goal:** every model capability the platform needs, running free and locally, behind
ports that accept a hosted provider by configuration.

| ID | Task | Deliverable |
|---|---|---|
| M2-T1 | Ports: `EmbeddingProvider`, `RerankProvider`, `GenerationProvider`, `ClassificationProvider` | Four capability roles |
| M2-T2 | `sentence-transformers` adapter — `bge-small-en-v1.5`, thread-pool offload, batching | ~10 ms/short text on CPU |
| M2-T3 | Cross-encoder adapter — `bge-reranker-base` | ~400 ms / 20 pairs on CPU |
| M2-T4 | Ollama adapter via LiteLLM; model pull manifest in compose | Qwen2.5-3B default |
| M2-T5 | **Embedding-centroid intent classifier** — labelled exemplars, no LLM | The default `classification` path |
| M2-T6 | `ModelTier` bundles: `cpu-minimal`, `cpu-standard`, `gpu-8gb`, `hosted` | One env var flips the stack |
| M2-T7 | `scripts/calibrate_compute_units.py` — benchmark at setup, persist normalization | Provider-agnostic cost unit |
| M2-T8 | Routing: capability × latency × compute cost; circuit breaker per provider | Local is always a fallback target |
| M2-T9 | Caching: embedding (30 d), rerank (6 h), completion (1 h) — all version-keyed | Redis, org-prefixed |
| M2-T10 | Single-owner retry: Tenacity wraps; **provider SDK retries disabled** | No compounding retry storms |
| M2-T11 | Migration: `inference_route`, `inference_call` (monthly partitions) | `compute_units` + `usd_cost` both recorded |
| M2-T12 | `safetensors`-only loading, pinned model revisions, checksum verification | Threat T6 |

**Exit criteria**
- Full embedding + rerank + generation with **no API key present in the environment**.
- Setting `MNEMOS_OPENAI_API_KEY` and switching tier routes to OpenAI with zero code change.
- Killing Ollama degrades generation but leaves retrieval fully functional.

---

## M3 — Memory substrate

**Goal:** bitemporal claims with lineage, arbitration, and a lifecycle engine.

| ID | Task | Deliverable |
|---|---|---|
| M3-T1 | Domain: `Claim`, `MemoryKind`, `ValidityInterval`, `BeliefInterval`, `TrustTier` | Frozen models, newtyped IDs |
| M3-T2 | Migration: `subject`, `memory`, `memory_edge` | Schema per DatabaseDesign §4 |
| M3-T3 | **Exclusion constraint** on `(org, subject, predicate, scope_hash, valid_range)`, partial by kind | The invariant, enforced by the DB |
| M3-T4 | Indexes: partial-on-asserted, GiST validity, content-hash dedup, FTS, trigram | Hot paths exclude retracted rows |
| M3-T5 | `WriteClaim` use case: arbitration + supersession + outbox, **one transaction** | Returns the `arbitration` block |
| M3-T6 | `QueryClaims`: independent `as_of` (world) and `believed_at` (belief) axes | The audit question is answerable |
| M3-T7 | `RetractClaim` — closes belief time, never deletes | Distinct from erase |
| M3-T8 | `domain/policies.py`: importance, exponential decay per kind, use-based reinforcement | Pure functions |
| M3-T9 | Celery beat: decay sweep, advisory-lock leader election | Idempotent, resumable |
| M3-T10 | Consolidation: cluster episodic → semantic `reflection` + `DERIVED_FROM` edges | Lineage preserved |
| M3-T11 | Compaction: summarize → tombstone. **Distinct from erase.** | Three-tier forgetting |
| M3-T12 | `EraseClaim` — DSR hard delete, cascades, re-embeds derived summaries | Irreversible, audited, separate permission |
| M3-T13 | Outbox table + relay with leader election | At-least-once, no lost events |
| M3-T14 | Property tests: decay monotonic/bounded; overlap raises for semantic, not episodic | Hypothesis |

**Exit criteria**
- Writing a contradicting claim supersedes the prior one and returns what it superseded.
- `as_of=T1&believed_at=T2` returns the historically correct answer for all four
  quadrants of the bitemporal square.
- Decay never deletes anything.

---

## M4 — Retrieval fabric

**Goal:** ACL-pushed-down lexical, vector, and hybrid retrieval.

| ID | Task | Deliverable |
|---|---|---|
| M4-T1 | Ports: `LexicalIndex`, `VectorIndex`, plus the `Candidate` envelope | Uniform result shape |
| M4-T2 | Migration: `embedding_space`, `memory_embedding` with **denormalized ACL columns** | Predicate evaluable inside the scan |
| M4-T3 | HNSW index (`halfvec`, cosine, m=16, ef_construction=64) | Per DatabaseDesign §4 |
| M4-T4 | **ACL pushdown**: `AuthorizationPredicate` → SQL `WHERE`, never post-filter | The core control |
| M4-T5 | Filtered-ANN recall: pgvector iterative scan + bounded `max_scan_tuples` + exact-scan fallback under high selectivity | Recall preserved under filters |
| M4-T6 | Lexical operator: `tsvector` + GIN, `ts_rank_cd`, trigram fallback | |
| M4-T7 | `MemoryScan` operator: bitemporal + kind + scope filters | |
| M4-T8 | RRF fusion (k=60) | Scale-free across scorers |
| M4-T9 | Rerank gate: score-margin heuristic | 10–30% fire rate target |
| M4-T10 | Dedup: content hash → SimHash/MinHash → semantic cluster | `merged_into` provenance |
| M4-T11 | Async indexing consumer: `memory.created` → embed → index → projection | Eventual, seconds |
| M4-T12 | **Recall test**: pushdown vs post-filter with 90% of the corpus inaccessible | Asserted as an inequality |

**Exit criteria**
- Hybrid search returns only authorized results, with the predicate visible in the query plan.
- The recall test proves post-filtering is worse — so a future "optimization" back to it fails CI.

---

## M5 — The Context Compiler ⭐

**Goal:** the thesis, working end to end, with `EXPLAIN`.

| ID | Task | Deliverable |
|---|---|---|
| M5-T1 | Domain: `ContextIR`, `IntentSignature`, operator algebra (closed set), `LogicalPlan`, `PhysicalPlan`, `CostVector` | Types before behaviour |
| M5-T2 | **Phase 1 Bind**: intent (centroid classifier), entity binding, policy binding | Ambiguity → `ClarificationRequired`, never a guess |
| M5-T3 | **Phase 2 Logical planning**: IR → operator DAG | |
| M5-T4 | Rewrite R1 — ACL pushdown | One module, independently tested |
| M5-T5 | Rewrites R2–R6 — projection pruning, fusion, branch elimination, pin folding, window collapse | One module each |
| M5-T6 | Migration + adapter: `operator_stats` catalog with `catalog_version` | The `ANALYZE` analogue |
| M5-T7 | Stats refresh job from OTel aggregates + feedback → `utility_prior` EWMA | Closes the learning loop |
| M5-T8 | **Phase 3 Optimizer**: cost model + Lagrangian-relaxed greedy allocator with section floors/ceilings | `O(n log n)`, deterministic |
| M5-T9 | **Phase 4 Executor**: async DAG, per-operator deadlines, declared fallbacks, `DegradationEvent` | Never fails on one slow source |
| M5-T10 | **Phase 5 Refine**: conflict resolution with `contested` demotion (losers are not dropped) | |
| M5-T11 | Compression: truncate / extractive MMR / abstractive, allocator-selected | Rejects abstractive on CPU by cost |
| M5-T12 | **Phase 6 Assemble**: versioned sandboxed template, **trust fencing**, canonical digest | |
| M5-T13 | Migration: `context_bundle`, `bundle_item`, `context_plan` | `acl_rule_id` per item |
| M5-T14 | `POST /v1/context:compile` — inline vs `202` decided by the planner | |
| M5-T15 | **`GET …/explain`** — plans, actuals, allocator trace, `binding_constraint`, gates | The flagship feature |
| M5-T16 | `POST …:replay` — deterministic recompile with diff | |
| M5-T17 | `POST /v1/context:estimate` — plan and cost without executing | |
| M5-T18 | Golden bundle fixtures + CI regression gate | Frozen digests |
| M5-T19 | Feedback endpoint → `utility_prior` | |

**Exit criteria**
- Assembled tokens never exceed the budget, over randomized section configs (Hypothesis).
- Identical request + pinned versions ⇒ identical digest.
- Killing Neo4j yields a degraded bundle, not a 500, with the degradation recorded.
- `EXPLAIN` names the binding constraint and lists every eviction with a reason.
- **This is the demo that carries the project.**

---

## M6 — Flow A: RAG over unstructured PDFs

| ID | Task | Deliverable |
|---|---|---|
| M6-T1 | Migration: `document`, `chunk` with `char_start`/`char_end`/`heading_path` | Citable provenance |
| M6-T2 | PyMuPDF extraction; Tesseract OCR **only** when no text layer | Free, local |
| M6-T3 | Structure-aware chunking (headings, tables, overlap) | |
| M6-T4 | Presigned MinIO upload with metadata → registration → ingestion enqueue | Event-driven |
| M6-T5 | Ingestion worker: extract → chunk → embed → index; per-stage status + errors | Resumable |
| M6-T6 | `trust_tier` assignment at source (external ⇒ ≥ 4) | Threat T1 layer 1 |
| M6-T7 | `POST /v1/rag:answer` — compile → generate → cite | Returns `bundle_digest` |
| M6-T8 | Citations carry document, page, char range | |
| M6-T9 | E2E on a small public-domain PDF corpus | |

**Exit criteria** — every answer sentence traces to a character range; `EXPLAIN` shows
what was evicted for budget.

---

## M7 — Knowledge graph

| ID | Task | Deliverable |
|---|---|---|
| M7-T1 | Neo4j bootstrap: constraints + indexes; `GraphStore` port | |
| M7-T2 | **Org-scoped Cypher builder, no raw-query escape hatch** | CE has no RLS |
| M7-T3 | Entity extraction (local model / gliner-style), canonicalization, linking | Free |
| M7-T4 | Projection consumer: claims + edges → graph, idempotent | Postgres stays authoritative |
| M7-T5 | `GraphExpand` operator with depth cap + deadline | |
| M7-T6 | `scripts/rebuild_projections.py` + runbook | DR story |

**Exit criteria** — dropping the entire graph and rebuilding from the claim log produces
an identical projection.

---

## M8 — Flow B: NL2SQL

| ID | Task | Deliverable |
|---|---|---|
| M8-T1 | Migration: `sql_datasource` (encrypted DSN + `key_version`), `sql_run` | |
| M8-T2 | `SqlDialect` port; SQLite + PostgreSQL adapters | Free engines |
| M8-T3 | Introspection → **schema as memory claims** | Bitemporal schema drift, free |
| M8-T4 | `POST …:test` with inline credentials, pre-save | Never save a broken connection |
| M8-T5 | **`domain/safety.py`** — AST read-only guard (sqlglot), pure, no I/O | The critical function |
| M8-T6 | Table authorization: fail-closed allow-list; `denied_tables` surfaced to narration | |
| M8-T7 | Generation from a compiled bundle | Flow owns generation, kernel owns retrieval |
| M8-T8 | Bounded repair loop; **guard re-runs before every execution attempt** | Including repaired SQL |
| M8-T9 | Execution: read-only user, statement timeout, row cap | |
| M8-T10 | Narration with explicit partial/pruned-data acknowledgement | |
| M8-T11 | Human confirmation gate for high-impact plans | |
| M8-T12 | Exhaustive safety tests: DML in CTE / UNION / subquery; unparseable ⇒ reject | |

**Exit criteria** — no DML reaches a datasource under any tested input, including
adversarial repair-loop attempts; an unauthorized table never appears in the bundle.

---

## M9 — Agent runtime

| ID | Task | Deliverable |
|---|---|---|
| M9-T1 | Migration: `agent_definition`, `agent_run`, `agent_checkpoint` | Budgets persisted |
| M9-T2 | State machine with bounded back-edges; runtime-enforced budgets | Not prompt-enforced |
| M9-T3 | Checkpoint on every transition, recording the consumed `bundle_digest` | |
| M9-T4 | PLAN / ACT / OBSERVE / CRITIC / VERIFY steps | |
| M9-T5 | `AWAITING_APPROVAL` + resume token; pub/sub notification | HITL |
| M9-T6 | Cooperative cancellation over pub/sub | |
| M9-T7 | Crash recovery: resume from last checkpoint with budgets intact | |
| M9-T8 | **Step replay** against the exact original bundle | |
| M9-T9 | `min_trust_tier` computed and persisted per checkpoint | Threat T1 layer 3 input |

**Exit criteria** — killing a worker mid-run loses at most the in-flight step; a replayed
step consumes byte-identical context.

---

## M10 — Flow C: MCP tool service (separate entity)

| ID | Task | Deliverable |
|---|---|---|
| M10-T1 | Separate service + container + network boundary | Boundary ④ |
| M10-T2 | Migration: `mcp_server`, `mcp_tool`, `mcp_credential`, `mcp_grant`, `mcp_invocation` | |
| M10-T3 | Remote MCP client: SSE + streamable HTTP | |
| M10-T4 | MCP OAuth 2.0: dynamic client registration, consent callback, token storage | |
| M10-T5 | Per-user credential isolation, AES-GCM envelope encryption | No shared service identity exists |
| M10-T6 | Tool discovery + JSON Schema validation before dispatch | |
| M10-T7 | **Roles re-derived from DB per request** | Never from headers |
| M10-T8 | **Trust-tier re-authorization at the tool boundary**; error names the offending source | The control that works |
| M10-T9 | Grants: owner / role / user / admin | |
| M10-T10 | API→MCP generation from OpenAPI: deterministic templates, spec-validated | Optional local-LLM assist |
| M10-T11 | Mnemos-as-MCP-server: `memory.search`, `memory.write`, `context.compile`, `context.explain` | Makes it infrastructure |
| M10-T12 | Egress allow-list; SSRF guard incl. DNS-rebinding | |

**Exit criteria** — a tool call motivated by tier-5 content is denied with the offending
document named; Claude Desktop or any MCP client can use Mnemos as its memory layer.

---

## M11 — Dashboard and observability

| ID | Task | Deliverable |
|---|---|---|
| M11-T1 | Next.js + ShadCN + TanStack Query; OpenAPI-generated client | Never hand-written |
| M11-T2 | **Bundle inspector + `EXPLAIN` plan tree** (React Flow) | The flagship screen |
| M11-T3 | **Memory explorer with an as-of / believed-at time slider** | Bitemporality, visible |
| M11-T4 | Graph explorer | |
| M11-T5 | Agent timeline; each step links to its bundle | |
| M11-T6 | NL2SQL run viewer with per-attempt safety verdicts | |
| M11-T7 | MCP registry, grants, invocation log with trust-tier decisions | |
| M11-T8 | Compute-unit dashboard (per org, purpose, provider class) | |
| M11-T9 | Langfuse + OTel dashboards; the domain SLIs from SystemDesign §11 | |
| M11-T10 | WebSocket live updates | |

**Exit criteria** — an engineer can answer *"why was this in the context?"* entirely in
the UI, without a database query.

---

## M12 — Hardening and performance

| ID | Task | Deliverable |
|---|---|---|
| M12-T1 | Load test: measure the latency envelope in SystemDesign §2; **update the doc with real numbers** | Targets validated or revised |
| M12-T2 | Profile and tune HNSW `m` / `ef_search` / iterative-scan caps | |
| M12-T3 | Chaos: kill each dependency in turn, assert documented degradation | Failure table verified |
| M12-T4 | Query-count assertions; eliminate N+1 | |
| M12-T5 | Admission control + per-org fair queuing + load shedding by budget class | |
| M12-T6 | Full DSR export/erase incl. summary re-embedding | |
| M12-T7 | Key rotation job; crypto-shredding path | |
| M12-T8 | Security review against the ThreatModel §9 checklist | |
| M12-T9 | Module READMEs, sequence diagrams, public API docs | |
| M12-T10 | Demo dataset + scripted walkthrough + README GIFs | The thing people actually look at |

---

## Effort and honesty

| Milestone | Estimate (solo, part-time) | Cumulative |
|---|---|---|
| M0 | 1 week | 1 w |
| M1 | 2 weeks | 3 w |
| M2 | 1.5 weeks | 4.5 w |
| M3 | 2.5 weeks | 7 w |
| M4 | 2 weeks | 9 w |
| **M5** | **3.5 weeks** | **12.5 w** ← thesis complete |
| M6 | 2 weeks | 14.5 w |
| M7 | 1.5 weeks | 16 w |
| M8 | 2.5 weeks | 18.5 w |
| M9 | 2 weeks | 20.5 w |
| M10 | 3 weeks | 23.5 w |
| M11 | 3 weeks | 26.5 w |
| M12 | 2 weeks | 28.5 w |

**~7 months part-time for the whole thing; ~3 months to the thesis milestone.**

These are honest estimates for production-quality work with real tests, not a
motivational schedule. Two implications worth acting on:

1. **M0–M5 plus M6 is a complete, defensible artifact.** A context compiler with
   `EXPLAIN`, a bitemporal memory substrate, and one working flow is a stronger portfolio
   than three half-built flows. Ship that publicly first.
2. **Cut M11 before cutting tests.** A dashboard is replaceable by a good README with
   `EXPLAIN` output pasted in. Test coverage is not replaceable, and its absence is the
   first thing a senior reviewer checks.
