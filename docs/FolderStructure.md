# Folder Structure

**Shape:** feature-first at the top, clean-architecture layers inside each feature,
boundaries enforced by CI rather than convention.

---

## 1. Repository root

```
mnemos/
├── src/mnemos/                  # the Python package (src-layout)
├── tests/
├── frontend/                    # Next.js dashboard
├── docs/
├── deploy/
│   ├── compose/                 # docker-compose.{base,dev,obs}.yml
│   ├── nginx/
│   ├── postgres/                # init: extensions, roles, RLS bootstrap
│   ├── neo4j/                   # constraint + index bootstrap Cypher
│   └── ollama/                  # model pull manifest
├── migrations/                  # Alembic
│   ├── env.py
│   └── versions/
├── scripts/
│   ├── seed_demo.py
│   ├── calibrate_compute_units.py    # benchmarks local inference at setup
│   └── rebuild_projections.py        # Neo4j + read models from the claim log
├── .github/workflows/
├── Makefile
├── pyproject.toml
├── .pre-commit-config.yaml
├── .importlinter                # ← architecture, as an executable contract
└── .env.example
```

**`src/` layout, not a flat package.** A flat layout makes the local working directory
importable, so tests can pass against uninstalled code that would fail once packaged.
`src/` forces tests to run against the installed distribution, which is the only way the
packaging is ever actually verified.

## 2. The package

```
src/mnemos/
├── core/                        # cross-cutting kernel — imports nothing from features
│   ├── config.py                # Pydantic BaseSettings, validated at startup
│   ├── errors.py                # exception hierarchy → Problem Details mapping
│   ├── result.py                # Result[T, E] for expected failures
│   ├── ids.py                   # UUIDv7 generation
│   ├── clock.py                 # Clock protocol — never call datetime.now() directly
│   ├── pagination.py            # signed opaque cursors
│   ├── telemetry.py             # OTel + structlog binding
│   ├── di.py                    # container + provider registry
│   └── canonical.py             # canonical JSON + sha256 digests
│
├── platform/                    # shared driven adapters (infrastructure, not domain)
│   ├── db/                      # engine, async session, UnitOfWork, RLS GUC binding
│   ├── redis/
│   ├── broker/                  # RabbitMQ publisher/consumer, outbox relay
│   ├── objectstore/             # S3-compatible (MinIO)
│   └── inference/               # LiteLLM/Ollama/sentence-transformers adapters
│
├── features/                    # ── THE KERNEL ──
│   ├── identity/
│   ├── memory/
│   ├── retrieval/
│   ├── context/                 # ▲ the context compiler ▲
│   ├── knowledge/
│   ├── gateway/
│   └── observability/
│
├── flows/                       # ── CONSUMERS OF THE KERNEL ──
│   ├── rag/
│   ├── nl2sql/
│   ├── agent/
│   └── tools/                   # MCP — also a separate deployable
│
└── entrypoints/                 # driving adapters
    ├── api/                     # FastAPI app, middleware, router assembly
    ├── realtime/                # WebSocket service
    ├── mcp/                     # MCP server (SSE + streamable HTTP)
    ├── worker/                  # Celery app, task registration, beat schedule
    └── cli/                     # mnemosctl
```

## 3. Anatomy of a feature

Every feature has the same five directories. No exceptions — predictability across
features is worth more than a locally-optimal layout in any one of them.

```
features/memory/
├── domain/                      # ← imports NOTHING with I/O
│   ├── models.py                # Claim, MemoryKind, ValidityInterval, TrustTier
│   ├── events.py                # MemoryCreated, MemorySuperseded, MemoryTombstoned
│   ├── ports.py                 # MemoryRepository, MemoryIndex  (typing.Protocol)
│   ├── policies.py              # importance, decay, reinforcement — pure functions
│   └── errors.py
├── application/                 # use cases; orchestrates domain + ports
│   ├── write_claim.py           # arbitration + supersession, one transaction
│   ├── query_claims.py          # bitemporal as-of / believed-at resolution
│   ├── retract_claim.py
│   ├── consolidate.py
│   └── erase.py                 # DSR hard-delete, distinct from retract
├── adapters/                    # implements domain/ports.py
│   ├── postgres_repository.py
│   ├── pgvector_index.py
│   └── neo4j_projection.py
├── api/                         # driving adapter
│   ├── router.py
│   ├── schemas.py               # request/response DTOs — never domain models
│   └── dependencies.py
├── tasks/                       # Celery tasks: decay sweep, consolidation, compaction
└── contracts.py                 # ← the ONLY module other features may import
```

**`contracts.py` is the load-bearing file.** It re-exports the handful of types and
protocols a feature is willing to expose. Everything else is private. Without it,
"feature-first" degrades within months into a ball of mud with directories.

**`api/schemas.py` never uses domain models directly.** Serializing a domain model
couples the wire format to internal structure, so every refactor becomes a breaking API
change. The mapping is boilerplate; the decoupling is the point.

**`domain/policies.py` holds pure functions.** Importance scoring, decay curves, and
conflict arbitration are the parts most likely to need tuning and most in need of
property-based tests. Keeping them pure means testing them requires no database.

### The context compiler's internals

The one feature whose structure mirrors its concepts rather than the standard template:

```
features/context/
├── domain/
│   ├── ir.py                    # ContextIR, IntentSignature, AuthorizationPredicate
│   ├── operators.py             # the operator algebra (closed set)
│   ├── plan.py                  # LogicalPlan, PhysicalPlan, CostVector
│   ├── bundle.py                # ContextBundle, BundleItem, BudgetReport
│   └── ports.py                 # StatisticsCatalog, OperatorExecutor
├── application/
│   ├── bind.py                  # phase 1
│   ├── logical_planner.py       # phase 2
│   ├── rewrites/                # phase 2 — one module per rule
│   │   ├── r1_acl_pushdown.py
│   │   ├── r2_projection_pruning.py
│   │   ├── r3_operator_fusion.py
│   │   ├── r4_branch_elimination.py
│   │   ├── r5_pin_folding.py
│   │   └── r6_window_collapse.py
│   ├── optimizer/               # phase 3
│   │   ├── cost_model.py
│   │   └── allocator.py         # Lagrangian-relaxed greedy + local improvement
│   ├── executor.py              # phase 4 — deadline-bounded async DAG
│   ├── refine/                  # phase 5
│   │   ├── dedup.py
│   │   ├── conflicts.py
│   │   ├── fusion.py            # RRF
│   │   ├── rerank_gate.py       # margin heuristic
│   │   └── compress.py
│   ├── assemble.py              # phase 6 — trust fencing + canonical digest
│   ├── explain.py
│   └── replay.py
├── adapters/
│   ├── postgres_statistics.py
│   └── postgres_bundle_store.py
└── api/
```

**One module per rewrite rule.** Each is an independently testable
`LogicalPlan → LogicalPlan` function. A single `optimize()` function containing six
rules interleaved is untestable in exactly the way that matters — you cannot assert that
R1 fired without R3 interfering.

### The flows

```
flows/rag/
├── ingestion/                   # pdf extraction, OCR fallback, structural chunking
├── application/answer.py        # compile context → generate → cite
└── api/
flows/nl2sql/
├── domain/dialect.py            # SqlDialect port
├── domain/safety.py             # AST read-only analysis — pure, heavily tested
├── application/
│   ├── introspect.py            # schema → memory claims
│   ├── generate.py
│   ├── validate.py              # AST guard + table authorization
│   ├── execute.py               # bounded repair loop
│   └── narrate.py
├── adapters/{sqlite,postgres}_dialect.py
└── api/
flows/agent/
├── domain/state_machine.py      # states, transitions, persisted budgets
├── application/{plan,act,observe,critic,verify,reflect}.py
├── adapters/postgres_checkpoint_store.py
└── api/
flows/tools/                     # separate deployable
├── domain/{tool,transport,trust}.py
├── application/
│   ├── register_remote.py
│   ├── oauth_flow.py            # dynamic client registration + consent callback
│   ├── generate_from_openapi.py # deterministic templates, optional LLM assist
│   ├── discover.py
│   └── invoke.py                # trust-tier re-authorization at the boundary
├── adapters/{sse,streamable_http}_client.py
└── api/
```

`flows/nl2sql/domain/safety.py` sits in the **domain** layer with no I/O. The AST
read-only guard is the single most security-critical function in that flow, and it must
be testable exhaustively — including nested CTEs, `UNION`, and unparseable input — with
nothing but strings in and verdicts out.

## 4. Enforced boundaries

`.importlinter`:

```ini
[importlinter]
root_package = mnemos

[importlinter:contract:1]
name = Domain layers are pure
type = forbidden
source_modules =
    mnemos.features.*.domain
    mnemos.flows.*.domain
forbidden_modules =
    sqlalchemy
    redis
    neo4j
    httpx
    fastapi
    celery
    litellm

[importlinter:contract:2]
name = Clean architecture layering
type = layers
layers =
    mnemos.features.memory.api
    mnemos.features.memory.application
    mnemos.features.memory.domain
# …repeated per feature and flow

[importlinter:contract:3]
name = Features are independent except via contracts
type = independence
modules =
    mnemos.features.memory
    mnemos.features.retrieval
    mnemos.features.identity
    mnemos.features.knowledge
    mnemos.features.gateway

[importlinter:contract:4]
name = Flows depend on the kernel, never the reverse
type = forbidden
source_modules = mnemos.features
forbidden_modules = mnemos.flows

[importlinter:contract:5]
name = Core depends on nothing internal
type = forbidden
source_modules = mnemos.core
forbidden_modules =
    mnemos.features
    mnemos.flows
    mnemos.platform
    mnemos.entrypoints
```

Contract 4 is the one that keeps the thesis honest. The moment `features.context`
imports `flows.nl2sql`, the kernel has stopped being a kernel and has become a pile of
special cases. CI failing on that import is worth more than any amount of documentation
saying not to do it.

## 5. Tests

```
tests/
├── unit/                        # pure domain — no I/O, milliseconds
│   ├── features/context/test_allocator.py
│   ├── features/context/rewrites/test_r1_acl_pushdown.py
│   ├── features/memory/test_decay_policy.py
│   └── flows/nl2sql/test_sql_safety.py      # exhaustive DML/CTE/UNION cases
├── integration/                 # real Postgres/Redis/Neo4j via testcontainers
│   ├── test_bitemporal_constraints.py       # the exclusion constraint actually holds
│   ├── test_rls_isolation.py                # cross-tenant reads return zero rows
│   ├── test_outbox_delivery.py
│   └── test_acl_pushdown_recall.py          # pushdown vs post-filter recall
├── e2e/                         # full compose stack
│   ├── test_rag_flow.py
│   ├── test_nl2sql_flow.py
│   └── test_agent_mcp_flow.py
├── contract/                    # OpenAPI schema + Problem Details conformance
├── performance/                 # latency envelope vs SystemDesign §2
├── fixtures/
│   ├── golden_bundles/          # frozen digests — regression detection for context
│   └── corpora/                 # small public-domain PDFs, tiny SQLite datasets
└── conftest.py
```

**`fixtures/golden_bundles/` is the highest-value fixture directory in the repository.**
Frozen `(request, catalog_version, policy_version) → digest` triples. A change that
alters assembled context without an intentional version bump fails CI. This is only
possible because bundles are deterministic and content-addressed — it is the practical
payoff of that design decision, and the reason it was worth the cost.

## 6. Frontend

```
frontend/src/
├── app/                         # Next.js App Router
│   ├── memory/                  # bitemporal explorer with an as-of time slider
│   ├── context/[digest]/        # bundle inspector + EXPLAIN plan tree (React Flow)
│   ├── graph/                   # knowledge graph explorer
│   ├── runs/[id]/               # agent timeline with per-step bundle links
│   ├── sql/                     # NL2SQL runs + per-attempt safety verdicts
│   ├── tools/                   # MCP server registry, grants, invocation log
│   └── cost/                    # compute-unit dashboard
├── components/ui/               # ShadCN
├── lib/api/                     # generated from OpenAPI — never hand-written
└── stores/                      # Zustand
```

`lib/api/` is generated from the OpenAPI schema in CI. Hand-written clients drift from
the server, and the drift is always discovered in production.

## 7. Naming conventions

| Kind | Convention | Example |
|---|---|---|
| Modules | `snake_case`, singular | `write_claim.py` |
| Use cases | Verb phrase, one public entry point | `WriteClaim.execute()` |
| Ports | Noun, no `I` prefix | `MemoryRepository` |
| Adapters | `{technology}_{port}` | `PostgresMemoryRepository` |
| DTOs | `{Action}{Resource}{Request,Response}` | `CompileContextRequest` |
| Events | Past tense | `MemorySuperseded` |
| Celery tasks | `{feature}.{action}` | `memory.decay_sweep` |
| Migrations | `{seq}_{verb}_{object}` | `0007_add_memory_exclusion_constraint` |

No `IMemoryRepository`. Hungarian prefixes on interfaces are a C# habit that adds a
character of noise to every reference in exchange for information the type checker
already has.
