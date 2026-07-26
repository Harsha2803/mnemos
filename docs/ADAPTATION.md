# Mnemos — Build Plan & JIVA Adaptation Map

> **Read this first if you are resuming work.** It is the authoritative plan and is
> self-contained: architecture, capability map, schema, milestones, and current state.
> [`TRACKER.md`](../TRACKER.md) holds live task status; this holds the design.

**Last updated:** 2026-07-26

---

## 1. What Mnemos is

**An AI workspace chatbot.** One conversation surface. The user asks something; a router
decides whether the answer needs documents (**RAG**), a database (**NL2SQL**), a tool
(**MCP**), memory, or a combination — then answers with citations.

Underneath, every message has an inspectable **context bundle** and a **governed memory
layer** that distinguishes current facts from superseded ones.

**Positioning:** the app does many things. Context and memory management is the thing
that *stands out* among them — not the whole product.

**Constraints (non-negotiable):**
- **Zero monetary cost.** Every component free and self-hosted. No API key required.
- **Fully containerized.** Backend, worker, realtime, frontend in separate containers.
- **Portfolio-grade**, single-node. Production *practices*, not production *scale*.
- CPU-only target: 8 cores, ~21 GB RAM, no GPU.

---

## 2. IP boundary (read before touching `jiva/`)

`~/Personal/Projects/Resume_001/jiva/` is the author's **employer's proprietary codebase**
(J K Technosoft, project JIVA). It is reference material for *what to build*, never for
*what to copy*.

| Permitted | Forbidden |
|---|---|
| Architectural shape — which services exist, how modules split | Source code, verbatim or lightly edited |
| Capability lists — what a platform like this needs | Database schemas, migration bodies |
| Naming/layering conventions the author is fluent in | Prompts, domain registries, business vocabulary |
| Lessons (single-owner retry, fail-closed authz, split-horizon OIDC) | Client names, customer data, internal docs |

Every file in Mnemos is written fresh. **Patterns are portable; artifacts are not.**
A public personal repo containing employer code is a real legal problem for the author.

---

## 3. JIVA capability map → Mnemos

Surveyed from directory structure and router registration only.

| JIVA module | Mnemos equivalent | Notes |
|---|---|---|
| `auth_modules/providers/` (OIDC/SAML/APIKey/internal, Strategy+Factory) | `features/identity/providers/` | Internal + OIDC (Keycloak) only. Same Strategy+Factory recipe, 2 protocols not 4 |
| `user_management/{user,role,tag}` | `features/identity/` | Users, roles, RBAC, **tag-scoped document ACLs** |
| `commons/object_stores/{s3,gcs,azure}` | `platform/objectstore/` | Port + **S3 adapter on MinIO (free)**. GCS/Azure adapters code-complete, explicitly untested |
| `commons/client_ingestion/{s3,gcs,smb,sharepoint,db}_interface` + `init_client_storage` | `features/connectors/` | `SourceConnector` port + factory. Adapters: MinIO/S3, local FS, HTTP URL |
| `commons/messaging/{pubsub,sns,servicebus}` | `platform/events/` | `EventBus` port + **Redis Streams** adapter. No cloud pub/sub (costs money) |
| `ingestion/unstructured/{chunking,intelligent_processing,kg_schema}` | `features/knowledge/` | Extract → chunk → embed. Char offsets retained for PDF highlight |
| `ingestion/structured/connector/{6 warehouses}` | `features/datasources/` | **Postgres only** (free). `SqlDialect` port keeps others a config exercise |
| `retrieval_v2/src/nl2sql/` (11 numbered steps) | `flows/nl2sql/` | Compressed to 6 steps. **AST read-only guard + read-only DB role** (defence in depth) |
| `agentic/{agents,tools,workflows,intents}` | `flows/agent/` | Bounded state machine, checkpoints |
| `mcp_gateway` + `remote_mcp_connect` + `mcp_server_builder` | `features/tools/` | Registry, tool calling, per-user credentials, approval gates |
| `chat_history/` (bookmarks, feedback, folders) | `features/chat/` | Sessions, messages, bookmarks, feedback, folders |
| `prompt_store/` + `prompt_service/` | `features/prompts/` | **DB-backed versioned prompts, activatable.** High-signal, cheap |
| `cost_dashboard/` | `features/observability/` | Token/latency/cost ledger |
| `bulk_ingestion/` | `features/knowledge/jobs` | **Heartbeat + stuck-job detection + status history** |
| `deletion/` | `features/knowledge/` | Cascade delete + memory erase |
| `glossary_kpi/` | `features/datasources/glossary` | Business vocabulary feeding NL2SQL |
| `websocket/` (separate service) | `entrypoints/realtime/` | Separate container |
| `celery_worker/` | `entrypoints/worker/` | Separate container |
| `display_graph/` (Neo4j/Neptune) | **dropped** | Whole extra container + subsystem, marginal payoff here |
| SAML, Terraform, K8s, 6 warehouses | **dropped** | Cost / scope |

---

## 4. Service topology (all free)

| Container | Image / build | Port | Purpose |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | System of record + vectors. Second DB `mnemos_analytics` for NL2SQL |
| `redis` | `redis:7-alpine` | 6379 | Cache, locks, Streams event bus |
| `minio` | `minio/minio` | 9000/9001 | S3-compatible object storage |
| `keycloak` | `quay.io/keycloak/keycloak:26.0` | 8080 | Real OIDC. Realm auto-imported |
| `ollama` | `ollama/ollama` | 11434 | Qwen2.5 3B instruct |
| `migrate` | backend | — | One-shot `alembic upgrade head` before API |
| `api` | backend | 8000 | FastAPI |
| `worker` | backend | — | Ingestion jobs |
| `realtime` | backend | 8001 | WebSocket gateway |
| `web` | frontend | 3000 | Next.js |

Split-horizon OIDC is configured: browser uses `localhost:8080`, API uses `keycloak:8080`.
Collapsing these is the classic containerized-OIDC `iss` mismatch failure.

---

## 5. Backend package layout

```
backend/src/mnemos/
├── core/                  config · errors · logging · security · types · ids · clock
├── platform/              db · redis · objectstore · events · unitofwork
├── features/
│   ├── identity/          users, orgs, roles, tags, API keys
│   │   └── providers/     internal + OIDC (Strategy + Factory + composition root)
│   ├── memory/            bitemporal claims, supersession, lifecycle
│   ├── retrieval/         vector · lexical · memory operators, RRF, dedup, conflicts
│   ├── context/           the compiler: bind → plan → allocate → execute → refine → assemble
│   ├── knowledge/         documents, chunks, ingestion jobs (heartbeat, stuck detection)
│   ├── connectors/        SourceConnector port + factory (minio/s3, local fs, http)
│   ├── datasources/       SQL datasource registry, introspection, glossary
│   ├── chat/              sessions, messages, bookmarks, feedback, folders
│   ├── tools/             MCP registry, invocation, credentials, grants
│   ├── prompts/           versioned prompt store
│   └── observability/     cost ledger, traces
├── flows/
│   ├── rag/               answer over documents with citations
│   ├── nl2sql/            NL → schema context → SQL → AST guard → execute → narrate
│   ├── agent/             bounded state machine over tools
│   └── router/            classify message → flow(s)
└── entrypoints/
    ├── api/               FastAPI app, middleware, routers
    ├── worker/            ingestion loop
    ├── realtime/          WebSocket
    └── cli.py             mnemosctl
```

**Layering rule:** `domain` (pure) ← `application` ← `adapters`/`api`.
`features` must never import `flows`.

---

## 6. Database schema plan

Alembic, one logical change per revision, reversible.

**identity** — `org`, `app_user`, `role`, `role_binding`, `tag`, `user_tag`, `api_key`,
`identity_provider`, `session`

**memory** — `subject`, `memory` (bitemporal: `valid_from/valid_to` + `recorded_at/retracted_at`,
`EXCLUDE USING gist` on `(org, subject, predicate, scope_hash, valid_range)` partial by kind),
`memory_edge`, `memory_embedding` (`halfvec` + HNSW + denormalized ACL columns for pushdown)

**knowledge** — `document` (+ `valid_from`, `superseded`), `chunk` (char offsets, page,
heading), `chunk_embedding`, `ingest_job` (heartbeat_at, attempts, status history),
`ingest_job_event`

**chat** — `chat_session`, `chat_message`, `message_citation`, `bookmark`, `feedback`, `folder`

**context** — `context_bundle` (digest, budget report), `bundle_item` (source, operator,
score, tokens, trust tier, **acl_rule_id**), `context_plan`

**datasources** — `sql_datasource` (encrypted DSN), `sql_run` (per-attempt safety verdicts,
authorized/denied tables), `glossary_term`

**tools** — `mcp_server`, `mcp_tool`, `mcp_credential`, `mcp_grant`, `mcp_invocation`

**prompts** — `prompt`, `prompt_version` (activatable)

**observability** — `inference_call` (monthly partitions), `audit_log`

Every tenant-scoped table: `org_id` + RLS `FORCE` on `app.current_org` GUC.

---

## 7. Milestones

| ID | Milestone | Exit criteria |
|---|---|---|
| **M1** | Container stack + backend skeleton | `docker compose up` → all healthy; `/healthz` 200 |
| **M2** | Alembic + full schema | `alembic upgrade head` clean; downgrade tested |
| **M3** | Identity: internal auth, JWT, RBAC, tags, OIDC via Strategy/Factory, API keys | Keycloak login → platform JWT; RLS blocks cross-org |
| **M4** | Port memory/retrieval/context kernel to Postgres + pgvector | Bitemporal tests pass on PG; ACL pushdown in EXPLAIN |
| **M5** | objectstore (MinIO) + connectors (port/factory) + Redis Streams events | Upload → bucket → event → consumer |
| **M6** | Knowledge: extract, chunk, embed, ingest jobs w/ heartbeat + stuck detection | PDF upload → searchable; killed worker → job resumes |
| **M7** | LLM gateway (Ollama) + versioned prompt store + cost ledger | Streaming generation; prompt version switch without redeploy |
| **M8** | Chat: sessions, messages, SSE streaming, bookmarks, feedback, folders | Multi-turn conversation persists |
| **M9** | RAG flow + per-message context inspector | Answer with citations → click → EXPLAIN |
| **M10** | NL2SQL: introspection, schema-as-claims, AST guard, read-only role, narration | DML rejected in CTE/UNION; unauthorized table never in bundle |
| **M11** | MCP tool runtime: registry, calling, per-user creds, approval gates | Tool call denied by trust tier names the offending source |
| **M12** | Router: classify → RAG / NL2SQL / tools / memory / chat | Correct flow chosen per message; shown in UI |
| **M13** | Next.js frontend: chat, memory, knowledge, data, tools, inspector, cost | All pages functional against the API |
| **M14** | Realtime WS, nginx, e2e verification, docs, push | Full stack from clean clone |

**Current position: M1 in progress.**

---

## 8. Current state

### Done
- Repo restructured: `backend/`, `frontend/`, `deploy/`, `docs/`
- `docker-compose.yml` — 10 services, all free, healthchecks, split-horizon OIDC
- `deploy/postgres/init/` — extensions (vector, pg_trgm, btree_gist, citext) + **separate
  `mnemos_analytics` DB with seeded demo warehouse and a `mnemos_ro` read-only role**
- `deploy/keycloak/mnemos-realm.json` — realm, `mnemos-web` public client w/ PKCE,
  3 roles, 3 seeded users
- `backend/Dockerfile` — multi-stage, non-root, venv
- `backend/pyproject.toml` — v0.2.0 dependency set
- `backend/src/mnemos/core/config.py` — settings, fail-fast, async-driver validator

### Carried over from v0.1 (needs porting from SQLite → Postgres)
`core.py`, `embed.py`, `store.py`, `retrieval.py`, `compiler.py`, `baseline.py`,
`ingest.py`, `dataset.py`, `bench.py`, `app.py`, `cli.py` — currently in
`backend/src/mnemos/` flat. **The kernel logic is sound and tested (23 tests); it needs
re-homing into the feature layout and re-targeting at asyncpg + pgvector.**

The v0.1 benchmark (naive prompt vs compiled bundle) should be **kept** — it is the
evidence for the memory/context differentiator. Re-point it at Postgres.

### Verified running (2026-07-26)

`docker compose up -d postgres redis minio` → all three healthy. Confirmed by query:

| Check | Result |
|---|---|
| Extensions in `mnemos` | `btree_gist citext pg_trgm plpgsql uuid-ossp vector` |
| Databases created | `mnemos`, `mnemos_analytics` |
| Analytics seed | 900 sales_order, 6 customer, 6 product, 4 region |
| `mnemos_ro` SELECT | allowed (900) |
| `mnemos_ro` INSERT | **`ERROR: permission denied for table region`** |

The last two lines are the defence-in-depth claim proven at the database level: even a
prompt injection that defeats the AST parser cannot write, because the role cannot write.

**Host port note:** this machine already runs Postgres on 5432 and Redis on 6379, so the
compose file maps host `15432 -> 5432` and `6380 -> 6379`. Container-to-container traffic
is unaffected and still uses the standard ports over the compose network.

### Not started
M2 onward. Not yet built or run: keycloak, ollama, and the four backend containers
(migrate/api/worker/realtime) — those need `backend/src/mnemos/entrypoints/api/main.py`
to exist first, which is the immediate next task.

---

## 9. Locked decisions

| Decision | Rationale |
|---|---|
| Ollama + Qwen2.5 3B | Best free CPU quality; native streaming; tool-calling for MCP |
| Postgres + pgvector, not SQLite | Real RLS, real exclusion constraints, real migrations |
| NL2SQL targets a **separate DB** with a **read-only role** | AST guard becomes the second line of defence, not the only one |
| Redis Streams, not cloud pub/sub | Free. Same port/adapter shape |
| MinIO, not S3 | Free. Same S3 API |
| Keycloak, not hand-rolled OIDC | Real protocol, free, matches the author's experience |
| Neo4j dropped | Extra container + subsystem; marginal payoff at this scope |
| Frontend: Next.js + TS + Tailwind | Free; matches the author's resume stack |
| Hashing embedder default, neural opt-in | Zero-download reproducibility |

---

## 10. Notes for the next session

- The v0.1 benchmark numbers in the root `README.md` were measured on SQLite. After the
  Postgres port, **re-run and update them** — do not let published numbers drift.
- `docs/` (Architecture, SystemDesign, DatabaseDesign, APIContract, ThreatModel, 12 ADRs)
  describes a larger target than what is built. That gap is stated in the README and is
  intentional; keep it stated.
- Known weakness carried from v0.1: brute-force cosine over all chunks per query. Fine at
  demo scale, must become a pgvector HNSW index query in M4.
- Do not re-run `pkill -f mnemos` — it matches the agent's own shell. Kill by port/PID.
