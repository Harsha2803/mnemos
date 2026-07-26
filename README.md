# Mnemos

**A context operating system for AI agents.**

Mnemos treats context as a *compiled artifact*, not a concatenated string. It takes a
request, a governance policy, and a resource budget, and produces a deterministic,
provenance-attributed, replayable **context bundle** — with an `EXPLAIN` for every
decision it made along the way.

> **Status:** Architecture phase. No implementation code yet — by design. The design
> documents in [`docs/`](docs/) are the current deliverable and are intended to be
> complete enough for another engineer to build from without further clarification.

---

## The thesis

Retrieval-augmented systems today assemble context the way early databases executed
queries: with a hand-written, fixed plan. You pick your `k`, you concatenate your
chunks, you hope it fits in the window.

Databases solved this with a **cost-based query optimizer**: declare *what* you want,
let a planner decide *how* to get it under a resource model, and expose `EXPLAIN` so
engineers can see and correct its reasoning.

Mnemos does that for context.

```
ContextRequest ──▶ Bind ──▶ Logical Plan ──▶ Cost-Based Optimizer ──▶ Physical Plan
                                                    │
                                              budget allocator
                                       (tokens × latency × dollars)
                                                    │
                              ┌─────────────────────▼─────────────────────┐
                              │  deadline-bounded async operator DAG      │
                              │  memory · vector · lexical · graph · docs │
                              └─────────────────────┬─────────────────────┘
                                                    │
              dedup ──▶ conflict resolution ──▶ rank ──▶ compress ──▶ assemble
                                                    │
                                                    ▼
                                          ContextBundle
                                   (content-addressed + manifest)
```

## Three pillars

Everything else in this repository is supporting infrastructure. These three are the
reason it exists.

### 1. The Context Compiler
A multi-phase compiler — bind, logically plan, cost-optimize, execute, assemble —
that allocates a hard token/latency/dollar budget across competing retrieval sources
using a statistics catalog and an explicit cost model. Emits a content-addressed
bundle whose every token traces to a source, a score, and the policy rule that
admitted it. `EXPLAIN CONTEXT` is a first-class API.

### 2. Bitemporal memory as governed claims
Memories are **claims with lifetimes and lineage**, not blobs. Every memory carries
*world time* (`valid_from` / `valid_to`) and *belief time* (`recorded_at` /
`retracted_at`), so the system can answer *"what did this agent believe on March 3rd,
and why?"* Updates never overwrite — they create supersession edges. Forgetting is
audited compaction (cluster → summarize → tombstone), kept strictly separate from
GDPR hard deletion.

### 3. Fail-closed authorization inside retrieval
Access control is pushed **into** the index predicate, never applied after ranking —
post-filtering leaks existence and destroys recall. A deny-by-default policy decision
point authorizes every candidate, and every admission is logged with the rule that
produced it. Retrieved content is **trust-tiered**: untrusted material is fenced at
assembly and can never acquire instruction authority or introduce new tool
permissions.

## Three flows, one kernel

An abstraction with a single consumer is speculation. Mnemos proves its context kernel
by driving three genuinely different consumers through the same operator algebra:

| Flow | Retrieves from | Proves |
|---|---|---|
| **RAG** — unstructured PDFs | chunks · memory · graph | Fusion and compression across heterogeneous scorers under a hard budget |
| **NL2SQL** — structured data | schema claims · glossary · exemplars · memory | Precision retrieval + *fail-closed* table authorization; AST-level read-only SQL enforcement |
| **Agent + MCP** — tools | tool catalogs · prior steps · tool output | Monotone trust tiers, multi-turn budgets, exact step replay |

`mnemos-tools` is a **separate deployable service**: MCP server exposing the kernel to
external agents, remote MCP client (SSE + streamable HTTP, OAuth 2.0 with dynamic client
registration), and generated API→MCP wrappers. It runs behind its own network boundary
because it executes third-party code paths on behalf of users.

Notably, none of the three flows contains retrieval logic. If any did, the kernel
abstraction would be a fiction.

## Zero cost by construction

**The default configuration requires no API key, no account, and no credit card.**

| Role | Free default | Paid alternative (config only) |
|---|---|---|
| Generation | Ollama · Qwen2.5-3B / Llama-3.2-3B | Any LiteLLM-supported provider |
| Embedding | `bge-small-en-v1.5` · CPU | OpenAI · Cohere · Voyage |
| Rerank | `bge-reranker-base` cross-encoder · CPU | Cohere Rerank |
| Intent classification | **no model** — embedding nearest-centroid, ~10 ms | Small hosted model |
| Object store | MinIO | S3 |
| Graph | Neo4j Community | Neo4j Enterprise / hosted |
| Tracing | Langfuse (self-hosted) | Langfuse Cloud |

Adding a hosted provider is one environment variable and a key — never a code change.

This constraint improved the design rather than compromising it. On CPU, one generation
call costs roughly **300× an embedding call**. That ratio is why intent classification
defaults to embeddings instead of an LLM (cheaper *and* more deterministic), why
reranking is gated on score margin, and why the budget allocator is load-bearing rather
than decorative. Cost is denominated in provider-agnostic `compute_units`, so the ledger
and the optimizer work identically whether the deployment is free or paid.

## Documentation

| Document | What it covers |
|---|---|
| [Architecture.md](docs/Architecture.md) | Thesis, pillars, layering, component model, ports |
| [SystemDesign.md](docs/SystemDesign.md) | Runtime topology, dataflow, sequences, scaling, failure modes |
| [DatabaseDesign.md](docs/DatabaseDesign.md) | PostgreSQL schema, bitemporal model, Neo4j, Redis keyspaces |
| [APIContract.md](docs/APIContract.md) | REST surface, error contract, pagination, versioning |
| [FolderStructure.md](docs/FolderStructure.md) | Feature-first layout with enforced layer boundaries |
| [CodingStandards.md](docs/CodingStandards.md) | Typing, async, DI, errors, testing rules |
| [ThreatModel.md](docs/ThreatModel.md) | STRIDE analysis, trust tiers, prompt-injection containment |
| [ImplementationPlan.md](docs/ImplementationPlan.md) | Milestones M0–M11 with exit criteria |
| [Roadmap.md](docs/Roadmap.md) | Sequencing, scope discipline, explicit non-goals |
| [DecisionLog.md](docs/DecisionLog.md) | Running log of decisions and their rationale |
| [ArchitectureDecisionRecords/](docs/ArchitectureDecisionRecords/) | Formal ADRs |

**Start here:** [Architecture.md](docs/Architecture.md), then
[ADR-0001](docs/ArchitectureDecisionRecords/ADR-0001-context-as-compiled-artifact.md).

**Building on this?** [`TRACKER.md`](TRACKER.md) is the live state file — current
milestone, non-negotiable constraints, and the next task fully specified. It is the only
file you need to read to resume work.

## Stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 16
(+ pgvector) · Redis · Neo4j Community · RabbitMQ · Celery · MinIO · Ollama ·
sentence-transformers · LiteLLM · Langfuse · OpenTelemetry · Docker Compose ·
Next.js · TypeScript · TanStack Query · React Flow

## Non-goals

Deliberately out of scope, so the novelty budget is not diluted:

- **Not a chat application.** The dashboard is an inspector and debugger.
- **Not a model training or evaluation platform.**
- **Not a multi-cloud storage abstraction.** One S3-compatible object-store port; that is all.
- **Not Kubernetes/Terraform.** Docker Compose proves the architecture; orchestration is deployment detail.
- **No paid dependency in the default path.** Ever.

### Scope honesty

This is a portfolio-grade system built and exercised on a single machine at zero cost.
What that means concretely:

- **Kept** — the engineering that makes work legible as senior: typed domain models,
  CI-enforced layer boundaries, bitemporal correctness, fail-closed authorization,
  transactional outbox, replayable bundles, real tests, real migrations.
- **Not claimed** — HA failover, multi-region residency, or validated performance at
  scale. Where the design anticipates scale (tenant partition keys, ports behind every
  dependency) it does so because those are cheap now and expensive later, not because
  anything here has been proven at a million users. Scaling stages beyond single-node
  are labelled in [SystemDesign §7](docs/SystemDesign.md#7-scaling-what-is-built-vs-what-is-designed-for)
  as design intent, un-exercised.

## License

To be selected before first public release — see
[ADR-0012](docs/ArchitectureDecisionRecords/ADR-0012-licensing-and-openness.md).
