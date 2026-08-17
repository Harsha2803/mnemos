# Mnemos — Build Plan & Architecture

> **Read this first if you are resuming work.** It is the authoritative plan and is
> self-contained: architecture, the capability inventory, schema, milestones, and current
> state. [`TRACKER.md`](../TRACKER.md) holds live task status; this holds the design.

**Last updated:** 2026-08-17 — `A4` is implemented and live-verified. The chat surface now
routes every message to chat, RAG, or NL2SQL, persists and displays the compact reason, and
has no manual answer-mode selector. Phase A is complete; `B3` is next.

---

## 1. What Mnemos is

**An enterprise AI assistant.** One conversation surface. The user asks something; a
router decides whether the answer needs documents (**RAG**), a database (**NL2SQL**), a
tool (**MCP**), memory, or a combination — then answers with citations you can click
into. Underneath it is multi-tenant, authenticated, authorised and audited, because that
is what separates an assistant from a demo.

**The breadth is the achievement.** Conversation, retrieval, natural language over a
warehouse, tool calling, ingestion at scale, identity, governance and the operational
scaffolding around all of it — a platform of this kind is defined by having the whole
surface, not by having one part of it done unusually well. §3 is the inventory, and every
row of it is in the milestone plan rather than in a wish list.

**It carries one deep technical claim, and the claim is measured rather than asserted:**
every prompt is a **compiled, budgeted artifact you can open** — an inspectable context
bundle over a **governed memory layer** that distinguishes current facts from superseded
ones. The numbers are in the root [`README.md`](../README.md). They were measured on the
v0.1 SQLite kernel and must be re-run when that kernel finishes its port in `C4`; until
then the README says so.

That is the ordering, and it used to be the other way round. Framing the project as a
context-compilation result that used a chatbot as its harness put the product last: the
old milestone plan reached a conversation surface at `M8`. The re-cut in §7 fixes the
order, and TRACKER **C14** is the rule that keeps it fixed.

**It is an independent implementation.** Every file is written fresh, and no other
codebase is a source. See §2.

**Constraints (non-negotiable):**
- **Zero monetary cost.** Every component free and self-hosted. No API key required.
- **Fully containerized.** Backend, worker, realtime, frontend in separate containers.
- **Portfolio-grade**, single-node. Production *practices*, not production *scale*.
- CPU-only target: 8 cores, ~21 GB RAM, no GPU.

---

## 2. IP boundary — this is an independent implementation

Mnemos implements capabilities the author has **production experience building**. It is
not derived from any system he has worked on, and specifically: **the author's employer's
codebase is not a reference. It is not read, not mapped from, and not cited.** That is
TRACKER **C11**, and it is a constraint rather than a preference.

The distinction the project runs on:

- **What a platform of this kind needs is public knowledge about the shape of the
  problem.** That it wants OIDC behind a provider seam, tenant-scoped RBAC, object
  storage behind a port, an event bus, structure-aware chunking, a read-only guard in
  front of generated SQL, a tool registry with approval gates, versioned prompts and a
  cost ledger is the *inventory in §3*. Any competent engineer arrives at that list from
  the problem statement, and much of it is in vendor documentation and conference talks.
- **Any particular codebase's realisation of that list is not public knowledge**, and
  none is consulted here. No source, no schema, no migration, no prompt, no domain
  registry, no business vocabulary, no client name and no internal document from anywhere
  else appears in this repository, verbatim or paraphrased.

Every design decision here is therefore justified from first principles, in §9 and in
`docs/ArchitectureDecisionRecords/`. That is not decoration: **a rationale that cannot be
written down from public reasoning does not go in**, because a decision whose only
justification is "that is how the other system did it" is exactly the kind this boundary
excludes.

**Why the section stays, rather than being deleted as obvious.** A personal repository
that documents itself as a mapping *from* an employer's system invites the reading that it
contains that employer's material — and that reading is expensive to disprove and cheap to
prevent. Stating the boundary explicitly is the protection; the earlier version of this
section, which described what could be safely taken from where, was the risk it was
supposed to guard against.

---

## 3. Capability inventory

What a platform of this kind needs, what Mnemos builds for it, and which milestone owns
it. Milestone IDs are the ones in §7; nothing here is aspirational, and anything
deliberately out of scope says so with its reason.

| Capability a platform of this kind needs | What Mnemos builds | Milestone |
|---|---|---|
| **Pluggable authentication** — more than one way to prove who you are, chosen per tenant rather than compiled in | `features/identity/providers/`: a Strategy + Factory over **two** protocols — a credential the caller knows, and a token another system minted. Internal password auth + OIDC on Keycloak. SAML is dropped (§9): it is a third adapter behind the same seam and proves nothing the second one did not | `M3.1`–`M3.3` ✅ |
| **A session that survives a reload, and a door that is shut by default** | Platform JWT (HS256) with refresh-token rotation and family revocation; a fail-closed route dependency where an undecorated route is authenticated, and public routes are an enumerated allow-list rather than a prefix match | `M3.4` ✅ backend · `A0` |
| **Users, roles, and per-document access that is not all-or-nothing** | `features/identity/`: users, orgs, system roles seeded at bootstrap, an RBAC permission matrix, **tag-scoped document ACLs**, API keys as a second credential type, and per-tenant row-level security under all of it | `M2a` ✅ RLS · `M3.7` ✅ roles · `C1` |
| **Object storage behind a port**, so the deployment target is a config choice | `platform/objectstore/`: port + S3 adapter on **MinIO** rather than S3 itself — same API, no bill, and the constraint that keeps the benchmark reproducible on any machine (C1) | `A2` upload · `B1` |
| **Source connectors** — content arrives from somewhere that is not an upload form | `features/connectors/`: a `SourceConnector` port + factory, with MinIO/S3, local filesystem and HTTP URL adapters. The abstraction is the deliverable; the adapter count is not | `B1` |
| **An event bus** decoupling ingestion from the request that triggered it | `platform/events/`: an `EventBus` port with a **Redis Streams** adapter. No cloud pub/sub — it costs money and it is the same port shape, so paying for it would buy nothing the port does not already give | `B1` |
| **Document ingestion** — extract, chunk, embed | `features/knowledge/`: extraction, structure-aware chunking with **char offsets retained** so a citation can highlight the exact span in the source PDF, and embedding into pgvector | `A2` |
| **Ingestion that survives failure at scale** | `features/knowledge/jobs`: heartbeat, attempt counting, status history, and a reaper that surfaces a **stuck** job rather than losing it silently. A job that dies quietly is the failure mode that makes an ingestion pipeline untrustworthy | `B2` |
| **Retrieval that is authorised during the scan, not after it** | `features/retrieval/`: vector, lexical and memory operators, RRF fusion, dedup, conflict resolution, with the authorization predicate pushed into the scan (C4). Ported from the v0.1 kernel onto pgvector HNSW | `A2` |
| **Answers grounded in documents, with citations that click through** | `flows/rag/` | `A2` |
| **Natural language over a warehouse** | `flows/nl2sql/`: introspection → glossary → generate → **AST read-only guard** → execute as a read-only DB role → narrate. Two independent defences, because a guard that is the only defence is one parser bug from a write | `A3` |
| **A SQL surface that is a config exercise to widen** | `features/datasources/`: datasource registry, schema introspection, and a `SqlDialect` port. **Postgres only** — the second warehouse is a paid account, and the port is what makes it a config exercise rather than a rewrite | `A3` |
| **Business vocabulary** — "revenue" means something specific here | `features/datasources/glossary`: glossary terms feeding the NL2SQL schema context | `A3` |
| **Routing**, so the user does not have to pick a mode | `flows/router/`: classify a message to chat / RAG / NL2SQL / tools, and show *why* it was routed there | `A4` |
| **A tool runtime with a trust boundary** | `features/tools/`: MCP registry, per-user credentials, trust tiers, approval gates, invocation records. A denial names the offending source on screen | `B3` |
| **Multi-step work that can be inspected mid-flight** | `flows/agent/`: a bounded state machine over tools with checkpoints and a step trace | `B4` |
| **Conversation persistence** — sessions, messages, streaming | `features/chat/`: `chat_session` + `chat_message`, SSE token streaming | `A1` |
| **Conversation *management*** — the part that makes it usable past the first week | `features/chat/`: folders, bookmarks, feedback, search over history | `C3` |
| **Prompts as data, not as string literals in a handler** | `features/prompts/`: DB-backed versioned prompts with diff and activation. Cheap to build, and the difference between tuning a prompt and redeploying to tune a prompt | `C2` |
| **Cost and token accounting** | `features/observability/`: an `inference_call` ledger (monthly partitions) behind a cost dashboard | `C2` |
| **An audit trail** | `features/observability/`: `audit_log` — who did what, readable in the UI | `C3` |
| **Governed context** — the deep claim | `features/memory/` (bitemporal claims, supersession, lifecycle) + `features/context/` (the six-phase compiler) + the context inspector + the benchmark re-run on Postgres | `C4` |
| **Deletion that reaches everything a document touched** | Cascade delete of document → chunks → embeddings → citations; memory erase lands with the memory layer | `A2` documents · `C4` memory |
| **Realtime push** — a separate service, because a WebSocket gateway and a request/response API have different lifecycles | `entrypoints/realtime/`: WS over Redis pub/sub, its own container since `M1` | `M1` ✅ container · `D1` |
| **Background execution** — same reason | `entrypoints/worker/`: its own container since `M1`; the job machinery it runs is `B2` | `M1` ✅ container · `B2` |
| **A knowledge graph** | **Dropped.** A whole extra container and subsystem (Neo4j) for a payoff that is marginal at this scope, against a retrieval path that already fuses three operators | — |
| **Terraform, Kubernetes, multi-node** | **Dropped.** Mnemos is portfolio-grade and single-node: production *practices*, not production *scale*. `docs/` describes the scaling stages and labels them as design intent | — |

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

Re-cut on 2026-08-02 into four phases. The old `M1`–`M14` numbering is superseded; it is
mapped onto these IDs at the end of this section, so a reference to an old ID found
anywhere translates rather than needing to be guessed at. The authoritative copy of these
tables is [TRACKER §3.0](../TRACKER.md#30-the-plan--four-phases-and-the-sentence-each-one-earns).

Two rules govern every row.

- **Both halves land** (TRACKER C12). A milestone with an untouched `frontend/` is not
  complete. Backend and UI advance together or the milestone does not close.
- **It ends with something a person can do** (TRACKER C14) — a sentence of the form *"you
  can now ___"* that a stranger could perform at `http://localhost:3000`. The right-hand
  column below is not a summary; it is the exit criterion. A milestone that cannot produce
  that sentence is infrastructure, and infrastructure folds into the milestone it serves
  rather than standing alone in the plan.

**Phase A — make it a chatbot.** The product surface, in the order that makes it usable.

| ID | What it builds | You can now… | Status |
|---|---|---|---|
| **A0** | Sign-in screen + browser session handling (`M3.4`'s UI half) + the fail-closed route guard (deny by default) | **sign in through Keycloak, stay signed in across a reload, and sign out** — and no route added after this is reachable unauthenticated | ✅ 2026-08-03 |
| **A1** | LLM gateway (Ollama) · chat sessions + messages · SSE streaming · the chat surface | **talk to it** — ask a question and watch the answer stream in token by token | ✅ 2026-08-08 |
| **A2** | Upload → extract → chunk → embed (pgvector HNSW) · retrieval ported from `_v1` · RAG flow · citations · knowledge library | **upload a document and ask questions about it**, with citations you click into | ✅ 2026-08-11 (PR #14) |
| **A3** | NL2SQL: introspection · glossary · generate · AST read-only guard · `mnemos_ro` execution · narration · SQL panel | **ask a question about your data in English** and see the SQL, the rows and the narration — and see the guard visibly refuse a write | ✅ 2026-08-15 (PR #15) — verified end to end in a real browser |
| **A4** | Router: classify a message → chat / RAG / NL2SQL · flow indicator | **ask anything without choosing a mode**, and see which flow answered and why | ✅ 2026-08-17 — verified end to end against the rebuilt stack |

**At the end of Phase A the thing this project is for exists.** Everything after deepens it.

**Build order deviates from phase order once, starting 2026-08-15: `B1`/`B2` come right
after `A3`, before `A4`.** [TRACKER's 2026-08-15 (evening) note](../TRACKER.md#5-next-task)
has the reasoning; [TRACKER §5's "Then, in order" list](../TRACKER.md#5-next-task) is
authoritative for sequencing, not these tables' phase grouping.

**Phase B — make it a platform.**

| ID | What it builds | You can now… | Status |
|---|---|---|---|
| **B1** | Object storage · source connectors (MinIO/S3, local FS, HTTP) · Redis Streams event bus · sources UI | **connect a source, browse it, and watch ingestion events arrive live** | ✅ 2026-08-17 — all 5/5 deliverables done, browser-verified against the rebuilt stack |
| **B2** | Ingestion jobs at scale: heartbeat, retries, status history, stuck-job reaper · per-job progress UI | **ingest a folder and watch every job's progress — including one that dies, surfaced as stuck rather than silently lost** | ✅ 2026-08-17 — verified against the rebuilt stack |
| **B3** | MCP tool runtime: registry, per-user credentials, trust tiers, approval gates · tool console | **register a tool, have the assistant call it, and approve a gated call** — with a denial that names the offending source on screen | ⬜ |
| **B4** | Agent flow: bounded state machine over tools, checkpoints, step trace | **give it a multi-step task and watch it plan, call tools and finish — with every step inspectable** | ⬜ |

**Phase C — make it enterprise, and land the deep claim.**

| ID | What it builds | You can now… | Status |
|---|---|---|---|
| **C1** | API keys · full RBAC permission matrix + tag-scoped document ACLs · keys UI + real 403 states | **issue an API key, call the API with it, and watch a user without the permission be refused** — in the UI and at the wire | ⬜ |
| **C2** | Versioned prompt store (diff, activate) · cost + token ledger · prompt manager + cost dashboard | **change the prompt behind a flow, activate the new version, and see what every answer cost** | ⬜ |
| **C3** | Chat history depth: folders, bookmarks, feedback · audit log · search over history | **organise, bookmark, rate and search your conversations, and read the audit trail of who did what** | ⬜ |
| **C4** | **The context layer.** Bitemporal memory + supersession · the budgeted context compiler · the context inspector · re-run the benchmark on Postgres | **open any answer and see its compiled context** — what was admitted, what was excluded and why, and the token spend against budget | ⬜ |

**Phase D — ship it.**

| ID | What it builds | You can now… | Status |
|---|---|---|---|
| **D1** | Realtime WebSocket presence + streaming polish · nginx · Playwright e2e over the whole stack · README rewritten on measured numbers | **run one command, get the whole system, and read a README whose every number was produced by a command in the repo** | ⬜ |

**Already built — the foundation the above stands on.**

| ID | What it built | Status |
|---|---|---|
| **M1** | Container stack, backend skeleton | ✅ |
| **M2** | Alembic + 41-table schema | ✅ |
| **M2a** | Tenant isolation made real — the unprivileged app role and the RLS policy fix | ✅ |
| **M3.1**–**M3.3** | Identity domain types · the provider seam (internal + OIDC) · the split-horizon OIDC round trip | ✅ |
| **M3.4** (backend) | Platform JWT on HS256 · refresh rotation with family revocation · token endpoints | ✅ |
| **M3.7** | `mnemosctl bootstrap` — first org, admin, system roles, provider rows | ✅ |
| **F0** | The app shell: Next.js, design tokens, three-column layout, theming, primitives, generated API client | ✅ |
| **F0a** | CI — pytest, ruff, mypy `--strict`, `alembic check`, and the frontend gate on every PR | ✅ |

### Old milestone numbers, mapped

Nothing was dropped. `M4`–`M14` were re-cut, not discarded, and this is the translation:

| Old | New | Note |
|---|---|---|
| `M3.5` API keys | `C1` | Deferred: an API key is a second credential type, and nothing consumes the first one yet |
| `M3.6` RBAC | split — guard to `A0`, matrix to `C1` | The **fail-closed guard** moves early because every route added in Phase A must be covered by it; the permission *matrix* can wait for something to permission |
| `M4` kernel port | split — retrieval to `A2`, memory + compiler + inspector to `C4` | Retrieval lands where RAG needs it so it is never built twice; the governance layer is a deep slice of its own |
| `M5` objectstore/connectors/events | `B1` | Minimal upload lands in `A2`; the connector *abstraction* is `B1` |
| `M6` knowledge + jobs | split — extract/chunk/embed to `A2`, job machinery to `B2` | |
| `M7` LLM gateway + prompts + cost | split — gateway to `A1`, prompts + cost to `C2` | The gateway is a prerequisite for talking at all; prompt versioning is not |
| `M8` chat | split — sessions/messages/streaming to `A1`, folders/bookmarks/feedback to `C3` | |
| `M9` RAG | `A2` | |
| `M10` NL2SQL | `A3` | |
| `M11` MCP tools | `B3` | |
| `M12` router | `A4` | Moved **earlier**: without it the user has to pick a mode, which is not what a chatbot is |
| `M13` frontend | dissolved into `F0` + a UI slice per milestone | Dissolved 2026-08-02 and unchanged by the re-plan. "Build every screen at the end" guaranteed the APIs would be shaped without a consumer and that the whole UI would land as one unreviewable drop |
| `M14` realtime + e2e + docs | `D1` | |

The UI follows [`DesignSystem.md`](DesignSystem.md), which is normative. It is Mnemos's
own system — its own accent, neutrals and identity — informed by Apple's design resources
for typography, spatial rhythm, materials and motion character. §0 there records which
Apple assets are off-limits (SF Pro as a webfont, SF Symbols) and what is used instead.

**Current position.** `main` has `A0` (PR #11), `A1` (PR #13), `A2` (PR #14), `A3`
(PR #15), `B1` (PR #16), the per-session log files (PR #17), the out-of-band frontend
polish work (PR #18), and `B2` plus its final UI/correctness review (PR #19). `A4` is
complete and verified on `agent/a4-message-router`; publication is waiting only for renewed
personal `Harsha2803` authentication. Once closed, `B3` is next.

`M3`'s exit criterion "RLS blocks cross-org" turned out to be unmet by `M2` rather than
merely untested; that is written up in §8 and in
[TRACKER §3](../TRACKER.md#3-current-state--what-is-actually-built).

---

## 8. Current state

### Product polish — UI enhancement handoff (2026-08-17, not a milestone)

This pass turns the existing milestone screens into a more coherent operating surface
without inventing backend capabilities. The overview summarizes documents, sources,
active jobs, conversations, recent activity, and service readiness. Knowledge adds a
searchable/filterable document table and a per-file upload queue with validation, retry,
removal, and batch feedback. Sources adds provider-specific registration guidance, source
activity, item search/filter/select-all, and an expandable job timeline that exposes status
history, progress, attempts, owner, heartbeat, lease, errors, and copyable job IDs.

Chat's selection model now covers whole answers, citations, SQL runs, and the future bundle
view. Citation markers provide hover/focus previews and click through to an evidence
inspector with navigation; the transcript respects manual scroll position; the conversation
list is searchable and grouped by recency. The SQL panel makes authorization and denial
explicit, keeps results labelled and copyable, and exposes execution metadata. Shell widths,
pinning, and collapsed state persist in an allowlisted non-sensitive preference record; the
authentication storage test continues to reject credentials or unknown keys.

Verification against the rebuilt stack: backend `make test` (433 passed), `make lint`,
`make types`, and `make check`; frontend `npm run test` (112 passed), `npm run lint`,
`npm run typecheck`, and `npm run build`; `docker compose up -d --build` with api/web and
stateful dependencies healthy; `/readyz` with Postgres, Redis, Ollama, and object storage
all `ok`; and the complete Playwright suite, 12/12 passed (auth, storage safety, chat,
upload/RAG/citations, allowed and denied NL2SQL, and Sources ingestion). This remains
out-of-band polish: it does not claim `A4`'s classifier or `C4`'s context-bundle compiler.

### Dev tooling — per-session log files (2026-08-16, not a milestone)

Not part of the `A`/`B`/`C`/`D` plan in §7 — an out-of-band developer convenience, so it
gets no milestone id and does not move `B1`'s "next task" status. `core/logging.py` can
now, opt-in (`Settings.session_log_enabled`, off by default), append every log line that
carries a `session_id` to its own file at `logs/sessions/{session_id}.log` — a login
session's whole activity, pullable by id later, rather than grepped out of the container
log stream. `entrypoints/api/security.py`'s `enforce_authentication` binds the resolved
caller's `org_id`/`user_id`/`session_id` to contextvars for the duration of the request
(and, via `bind_caller_context`/`reset_caller_context`, for `main.py`'s post-`call_next`
`http.request` summary line too — dependency teardown runs *inside* `call_next`, so the
middleware has to re-bind from `request.state.caller` rather than reuse the dependency's
already-reset binding). `docker-compose.yml`'s `api` service turns the flag on and
bind-mounts `./logs`; a new one-shot `logs-init` service (same shape as `minio-init`)
`chown`s it to the image's unprivileged uid first, since a fresh clone has no `./logs`
and Docker would otherwise auto-create it owned by root. `logs/`/`*.log` were already
gitignored. Full detail, including a `cache_logger_on_first_use` correctness bug this
surfaced in `configure_logging` itself, is in
[TRACKER's dated note](../TRACKER.md) for 2026-08-16.

### Product polish — seven frontend UI fixes (2026-08-16, not a milestone)

Also out-of-band, also no milestone id. A session is now titled from its own first
message rather than staying "New chat" forever (`features/chat/application/titles.py`,
shared by `ChatService`/`flows/rag`/`flows/nl2sql`); the sidebar's conversation rows
gained rename and delete controls; document uploads are checked against
`Settings.max_upload_bytes` client-side before anything is sent, and the picker/drop
zone now accept several files at once (one request per file, each failure named
separately); an open conversation reads at a new, wider `--chat-measure` token with a
tighter gutter instead of the document-route `measure`; and the sidebar now collapses/
resizes exactly like the inspector already did, plus draggable-and-keyboard-resizable
boundaries for both panels (the ARIA "window splitter" pattern). No schema change, no
migration. Live-verified against the running compose stack once it was free: a session
retitling itself from its first message with no reload, inline rename, delete-the-open-
session navigating back to `/chat`, the sidebar resize handle and collapse toggle, and a
real 26 MB file being refused client-side alongside a small file that uploaded
successfully. Full detail and evidence is in
[TRACKER's dated note](../TRACKER.md) for 2026-08-16.

### Product polish — hover-marquee titles + a motion pass (2026-08-16, not a milestone)

Also out-of-band, also no milestone id, same `feat/frontend-ui-fixes`/PR #18. Two pieces.
A long sidebar conversation title now scrolls into view on hover instead of staying
truncated forever — `MarqueeText` (`components/ui/`) measures real overflow and slides at
a constant speed, used first by `ChatSessionList.tsx`. Separately, a small, consistent
motion pass: every `Button` gets a press animation; both delete-confirmation dialogs
(chat and knowledge) fade/scale in and out via Radix's `data-state`; `EmptyState` settles
in with a fade+rise; a freshly-sent chat message does too, but its assistant reply
deliberately does not (it already arrives token by token, and its `id` swap on stream
completion would replay a mount animation a second time). All of it opacity/transform
only, so it collapses under `prefers-reduced-motion` for free. Full detail is in
[TRACKER's dated note](../TRACKER.md) for 2026-08-16 (later still).

### Product polish — chat transcript scrollbar (2026-08-16, not a milestone)

Also out-of-band, also no milestone id, same `feat/frontend-ui-fixes`/PR #18. The chat
transcript's scroll container (`chat/[sessionId]/page.tsx`) now carries a `.scrollbar-thin`
class (`globals.css`): a transparent track and a rounded, token-built thumb (`--fill-
secondary` at rest, `--fill` on hover, a `--bg`-matched inset border) instead of the bare
OS scrollbar — the shape ChatGPT's transcript scrollbar uses. Token-driven, so it tracks
light/dark like everything else; applied to the one pane the request named, not globally.
Live-verified in both themes. Full detail, including a note on the shared-compose-project
side effect this session's verification pass had on the concurrent `B1` session, is in
[TRACKER's dated note](../TRACKER.md) for 2026-08-16 (later).

### F0 — app shell ✅

The one task with no backend half, because `frontend/` was an empty directory and there
was nothing for a sign-in screen to be built *in*. Verified 2026-08-02.

- **Next.js 15 App Router, React 19, TypeScript `strict`** plus the four checks `strict`
  leaves off. `output: "standalone"`; `frontend/Dockerfile` is three stages in the same
  shape as `backend/Dockerfile` — dependency layer keyed on the manifest alone, build, then
  a runtime stage with no toolchain, running as uid 10001.
- **Tokens as the only source of colour** (C13). Every custom property from
  [`DesignSystem.md`](DesignSystem.md) §2 lives in `src/app/globals.css` and is mapped into
  Tailwind v4 through `@theme inline`. There is no `tailwind.config.js`, and
  `--color-*: initial` deletes Tailwind's built-in palette — without that, `bg-red-500`
  stays spellable, contains no hex literal, and defeats the grep that enforces the rule.
- **Theming with three preferences.** "Match system" is a real answer, so choosing it
  *removes* `data-theme` rather than setting it to `"system"` — a value that matches
  neither rule and would pin every OS-following user to light. A blocking inline script in
  `<head>` applies a stored choice before first paint.
- **The three-column shell** — 260px sidebar, content at the 46rem measure, 320px
  collapsible inspector, chrome on the translucent material with its opaque `@supports`
  fallback. Below 1024px the inspector becomes a Radix Dialog and below 768px the sidebar
  does too: a change of component, not of width, since a sheet traps focus and closes on
  Esc and a narrower column does neither.
- **Base primitives only** — `Button` (three ranks, no fourth), grouped-inset `List` with
  separators inset to the text origin, `EmptyState`, `Skeleton`, `ThemeToggle`. Every test
  queries by role and accessible name.
- **Generated API client.** `openapi-typescript` against the live `/openapi.json`, output
  committed, `npm run generate:api` in `package.json`. Nothing hand-written.
- **One real call end to end**: `/readyz` through the generated client and TanStack Query,
  rendered as a health indicator in the sidebar and a dependency list on the overview page.
  Each of the container, the CORS configuration, the generated types and the query layer
  already worked alone; this is what proves they work together.
- **`docker-compose.yml`**: `profiles: ["web"]` deleted and a healthcheck added, so plain
  `docker compose up -d` brings the frontend up and `docker compose ps` says something
  about a page rather than about a process.

Measured against the running stack and in headless Chrome over CDP:

```
docker compose ps    ->  web  Up (healthy), with api keycloak minio ollama
                         postgres realtime redis worker
curl -o /dev/null -w '%{http_code}' http://localhost:3000   ->  200
--dump-dom after JS  ->  "API ready" · "postgres" · "redis"

dark OS,  no choice   ->  data-theme=null   body bg rgb(11, 11, 15)
dark OS,  chose light ->  data-theme=light  body bg rgb(255, 255, 255)
light OS, chose dark  ->  data-theme=dark   body bg rgb(11, 11, 15)
sidebar 260px · inspector 320px · .measure 736px (= 46rem)
900px wide: inspector leaves the layout.  600px: sidebar leaves too.
CDP screencast over a hard reload, dark OS + stored light choice:
  13 frames, the first already light — no flash.
```

| Check | Result |
|---|---|
| `npm run test` | **41 passed** (Vitest + Testing Library + `vitest-axe`) |
| `npx tsc --noEmit` · `npm run lint` · `npm run build` | clean |
| `npm audit` | 0 vulnerabilities |
| axe on the shell | 0 violations |
| `pytest` · `alembic check` | **97 passed** · no drift — F0 changes no Python |

Deliberately absent at `F0`: any sign-in form (built in `A0`), any chat UI (`A1`),
any inspector *content*
(`C4`). The inspector renders an `EmptyState` saying so, because an empty pane with no
explanation reads as a bug and the user cannot tell "not built yet" from "broken".

### M1 — container stack + backend skeleton ✅

- Repo restructured: `backend/`, `frontend/`, `deploy/`, `docs/`
- `docker-compose.yml` — 10 services, all free, healthchecks, split-horizon OIDC
- `deploy/postgres/init/` — extensions (vector, pg_trgm, btree_gist, citext) + **separate
  `mnemos_analytics` DB with seeded demo warehouse and a `mnemos_ro` read-only role**
- `deploy/keycloak/mnemos-realm.json` — realm, `mnemos-web` public client w/ PKCE,
  3 roles, 3 seeded users
- `backend/Dockerfile` — multi-stage, non-root, venv
- `core/` — `config`, `errors`, `logging` (structlog + contextvars), `clock`, `ids`
  (UUIDv7), `types` (enums mirrored by CHECK constraints)
- `platform/` — `db` (async engine, tenant-scoped session setting the `app.current_org`
  GUC), `cache` (Redis, TTL-mandatory locks)
- `entrypoints/` — `api` (split `/healthz` liveness vs `/readyz` readiness), `worker`
  (stuck-job reaper), `realtime` (WS over Redis pub/sub), `cli` (`mnemosctl db doctor`)

### M2 — Alembic + full schema ✅

41 tables across the nine groups in §6. Four revisions at M2, each independently
reversible (`0005` and `0006` were added by M3 — see below):

| Revision | Contents |
|---|---|
| `0001` | All 41 tables, autogenerated from `mnemos.platform.models` |
| `0002` | `EXCLUDE USING gist` on `memory` + supersession-cycle trigger |
| `0003` | 25 monthly partitions for `inference_call`, anchored to a fixed month |
| `0004` | `FORCE ROW LEVEL SECURITY` + org-isolation policy on 40 tables |

`alembic check` is wired as the models-vs-migrations drift guard and currently reports
no diff. Downgrade to base was tested and leaves only `alembic_version`.

### A0 — the auth surface ✅

Verified 2026-08-03 on branch `feat/a0-auth-surface` (PR #11). **The first milestone that
earns a C14 sentence:** you can sign in through Keycloak at `http://localhost:3000`, stay
signed in across a reload, and sign out. Before it, `M3.4` issued tokens that nothing
presented and `F0` was a shell with no way in.

**Authenticated by default, public by enumeration.** The guard is an *application-level*
FastAPI dependency, so it is merged into every route the framework registers — routers
included later, routes added after startup, all of them. A route that decorates itself with
nothing is authenticated; the only way to be public is to be named in an **exact set of
literal paths**. Never a prefix: `/api/v1/auth` as a prefix would make a future
`/auth/users` public and the person adding it would have no reason to look at a list they
never touched. `/auth/me` is deliberately absent from the set and is therefore guarded,
which is precisely the property a prefix throws away.

| Layer | What landed |
|---|---|
| `entrypoints/api/security.py` | `enforce_authentication`, `public_route_paths()`, `require_caller` |
| `features/identity/application/principals.py` | `PrincipalResolver` — token in, `Principal` out; the `PrincipalRepository` port |
| `features/identity/adapters/principals.py` | The SQL. Four statements in one org-scoped transaction, so RLS is underneath every predicate |
| `entrypoints/api/routers/auth.py` | `GET /auth/me`; `authorize`/`callback` now answer a browser with redirects |
| `frontend/src/lib/auth/` | The in-memory token store, the single-flight refresh, the destination stash |
| `frontend/src/components/auth/` | Sign-in form, completion screen, auth boundary |
| `frontend/e2e/` | Playwright over the live stack |

**Roles and tags are read from the repository on every request, never from the token.**
`M3.4` kept authorization claims out of the token so a revoked role takes effect on the
next call rather than in fifteen minutes; that is only worth something if the reader
honours it. Proved against a real Postgres with **one token minted once and reused
verbatim**: no binding → `[]`, bound to `analyst` → `['knowledge:read', 'memory:read']`,
unbound → `[]`. The third step is the one an additive cache would fail, and it is the one
that keeps a demoted user's authority alive if it is missing.

The guard also checks that the `session` row named by `sid` is neither revoked nor expired.
Without it, signing out would revoke the refresh family and leave the access token working
until it expired — a sign-out with fifteen minutes' notice. A *rotated* predecessor stays
live: rotation retires a refresh token, it does not end a session.

**The browser never holds a token anywhere a script can read it.** The access token lives
in a module variable; the refresh token stays in the API's `httpOnly` cookie. A reload
loses the access token and recovers it by exchanging the cookie — the same call a 401
makes, so "stay signed in across a reload" and "recover from an expired token" cannot drift
apart. Concurrent 401s collapse into **one** refresh (within a tab, a shared promise;
across tabs, `navigator.locks`), because rotation treats a second presentation as theft and
kills the chain.

| Command | Result |
|---|---|
| `make test` | **230 passed** (was 191; +39) |
| `make lint` · `make types` | clean; `mypy --strict`, 106 source files |
| `make check` | "No new upgrade operations detected" — **no migration** |
| `npm run test` | **76 passed**, 11 files (was 41); `lint`, `tsc --noEmit`, `build`, `audit` clean |
| `npm run test:e2e` | **7 passed** in a real browser against the live Keycloak; **7 skipped** with the API stopped |
| CI | three jobs green, including `compose` — the images build and the stack starts |

**That e2e run closes `M3.4`'s one "could not verify".** Its live evidence drove
`authorize` and everything after the callback with `httpx`; what it could not do was fill
in Keycloak's own login form, because Keycloak 26 binds that form to a browser session
established with cookies on the auth page.

**Two deviations, both argued in [TRACKER §4](../TRACKER.md#4-known-gaps-and-honest-weaknesses)
items 34 and 35:** `authorize` and `callback` answer a browser with redirects rather than
JSON — one constant flag for every failure, and no token in any URL — and `GET /auth/me` is
pulled forward from `C1` because the shell has to name the signed-in user and the token
carries no email by design. It reports grants and enforces none; the permission matrix is
still `C1`.

### M3 — identity 🟡 in progress

**Done: the RLS prerequisite.** Verified 2026-07-27 on branch `feat/m3-identity`
(PR #2, draft).

M2 reported "40 tables with FORCE row-level security" as evidence of tenant isolation.
That report was accurate about the catalogue and wrong about the system. Writing M3's
acceptance test found two defects:

| Revision | Defect | Fix |
|---|---|---|
| `0005` | The application connected as `POSTGRES_USER`, created by the Postgres image as a **superuser**. RLS applies to neither a superuser nor a `BYPASSRLS` role, so every policy from `0004` was inert | Role split: `mnemos` owns the tables and runs Alembic; `mnemos_app` is `LOGIN NOSUPERUSER NOBYPASSRLS` with DML only and is what api/worker/realtime connect as. `mnemos_admin` is granted *to* `mnemos_app` for bootstrap |
| `0006` | An unscoped query **raised `22P02`** rather than returning zero rows: a reverted `SET LOCAL` leaves a dot-qualified placeholder GUC defined as `''`, not undefined, and `''::uuid` raises. Reproduces only on a connection that has already served a scoped request — i.e. every pooled one | Policy expression becomes `NULLIF(current_setting('app.current_org', true), '')::uuid`, restoring the failure mode `0004` documented |

Neither defect was reachable through a correctly filtered query — the explicit `org_id`
filter in §"Data access" of the coding standards held. What was absent is the *second*
layer that makes the defence-in-depth claim in `ThreatModel.md` true rather than
aspirational: an application bug was supposed to be caught by RLS, and RLS was off.

Evidence, as `mnemos_app` against the live stack, two orgs each owning one `tag` row:

| Check | Before | After |
|---|---|---|
| `SELECT count(*) FROM tag`, GUC = org A | 2 | **1** |
| Cross-org `INSERT` under GUC = org A | accepted | **rejected by the policy's `WITH CHECK`** |
| Same query on the same connection after `COMMIT` | `ERROR: invalid input syntax for type uuid: ""` | **0 rows** |

| Command | Result |
|---|---|
| `pytest` | **28 passed** — 23 `_v1` kernel + 5 new tenant-isolation tests |
| `alembic check` | no drift between models and migrations |
| `alembic downgrade 0004` then `upgrade head` | clean in both directions |

`tests/test_tenant_isolation.py` runs against a **testcontainers Postgres** with the real
extensions and the real revisions applied, not a fake — tenant isolation is a property of
Postgres, and a substitute would only prove the substitute isolates. Its
`test_application_role_holds_no_rls_exemption` asserts `rolsuper` and `rolbypassrls` are
both false on the live connection, because the regression it guards is a change to a DSN,
and no amount of correct SQL protects against that.

Also added: `Database.elevated_session()` — `SET LOCAL ROLE mnemos_admin` for the single
bootstrap transaction that has no org to scope to yet. A `SET ROLE` rather than a standing
privilege, because **role attributes are not inherited through membership**: `mnemos_app`
inherits `mnemos_admin`'s table privileges but not its `BYPASSRLS`, so escaping isolation
takes a deliberate statement visible in `pg_stat_activity` and at the call site.

**Done: M3.1 — the domain types (2026-08-02).** `features/identity/domain/` holds
`Principal`, `Permission`/`PermissionSet`, `TagSet`, `PrincipalKind`, and the id newtypes,
all pure and frozen, with **no SQLAlchemy in the layer** (proven by a subprocess import
test — an in-process check passes vacuously once pytest has loaded SQLAlchemy elsewhere).
Grants may be wildcards; requirements may not (`allows()` raises on a wildcard
requirement). Tag authorization is a set-overlap, kept that way so it pushes into the SQL
`WHERE` (C4). `pytest` 39 passed (+11), `ruff`/`mypy --strict` clean, `alembic check` clean.

**Done: M3.2 — the provider seam (2026-08-02).** `features/identity/providers/` turns a
presented credential into a verified `AuthenticatedSubject`. **Two protocols, not one**
(§3's "2 protocols not 4"): `CredentialAuthProvider` for a secret the caller knows,
`TokenAuthProvider` for a token another system minted. `ProviderFactory` reads the
`identity_provider` row and builds the strategy, so the login endpoint (M3.3) never
learns which one it got and SAML later is a row plus an adapter.

| File | What it is |
|---|---|
| `core/security.py` | `PasswordHasher` — argon2id at OWASP parameters (m=64 MiB, t=3, p=4), run on a worker thread because 64 MiB of mixing inline would freeze the event loop for every concurrent request. `verify(None, ...)` still performs a real verification, so "no such user" and "wrong password" cost the same. Plus `digest_token` (SHA-256, for high-entropy refresh tokens) and `tokens_equal` |
| `providers/base.py` | The two protocols, `AuthenticatedSubject`, and `denied()` — one constant message to the caller, the diagnostic reason to the log |
| `providers/ports.py` | `OrgDirectory` / `UserDirectory` + flat records. Persistence arrives through these, so `providers/` imports no ORM |
| `providers/internal.py` | `InternalProvider`. A user with `password_hash IS NULL` (external-IdP-only) cannot password-authenticate |
| `providers/oidc.py` | `OidcProvider` + `HttpJwksCache`. Signature, asymmetric-only algorithm allow-list, configured issuer, `aud`-or-`azp`, `exp` with no leeway |
| `providers/factory.py` | Strategy selection. Unknown org, disabled provider, unrecognised `kind`, incomplete OIDC config and an ambiguous default all deny identically |
| `adapters/directory.py` | The SQLAlchemy side of the ports |

**The authentication path needs no `BYPASSRLS`.** `org` is the one table without a policy —
it is what the policies compare against — so resolving an org slug runs unprivileged, and
every read after it runs with `app.current_org` bound to the org just resolved.
`Database.elevated_session()` therefore keeps its single bootstrap call site. That settles
the first of the two design questions the RLS work forced open, in favour of **carrying the
tenant in the credential**.

| Command | Result |
|---|---|
| `pytest` | **72 passed** in 6.5s (was 39; +33) |
| `ruff check` + `ruff format` | clean on all new files |
| `mypy --strict` | clean, 8 new source files (the 4 remaining project-wide errors are all in the quarantined `_v1/`) |
| `alembic check` | "No new upgrade operations detected" — M3.2 touched no schema |

Two deviations from the task as written, both deliberate and recorded in
[TRACKER §4](../TRACKER.md#4-known-gaps-and-honest-weaknesses): the OIDC validator trusts
**two** configured issuers rather than `issuer_internal` alone (Keycloak runs
`KC_HOSTNAME_STRICT=false`, so it stamps whichever host minted the token — accepting only
the internal URL would reject every token a browser can actually obtain), and the audience
check accepts the client id in `aud` **or** `azp`, which is the shape Keycloak access
tokens actually have.

**Done: M3.2a — the API error boundary (2026-08-02).** Found while reading
`entrypoints/api/main.py` to plan M3.3: the single `MnemosError` handler spread
`**exc.details` into the response body, so M3.2's deliberately-constant denial message was
being undone on the wire — a caller could read "no such user" versus "password mismatch"
straight out of a 401. `MnemosError.expose_details` now defaults to `False` and the handler
renders only `public_details`; `ValidationError` is the sole opt-in. Proved by restoring the
old handler and re-running `tests/test_error_boundary.py`, which returned the reason *and* a
DSN containing a password. The lesson generalises: every provider test passed before and
after, because they assert on the raised exception and never on the wire.

**Done: M3.3 — the OIDC round trip (2026-08-02).** `GET /api/v1/auth/oidc/authorize` →
Keycloak → `/callback` → verified subject. PKCE S256, `state` verified and single-use
(Redis `GETDEL`, so read-and-delete cannot interleave), the org read from stored state and
never from the callback's query string. `HttpOidcMetadata` caches discovery and is shared
with the JWKS cache; every discovered endpoint is constrained to the issuer's own prefix,
not just `jwks_uri`. `public_authorization_endpoint()` re-hosts the discovered path on
`issuer_public` — that function is split horizon in one place.

**The live realm settled the issuer question.** A genuine ID token from the seeded user
carries `iss = http://localhost:8080/realms/mnemos` — the *public* issuer — and
`aud = azp = mnemos-web`. Validating `iss` against `issuer_internal` alone, as the original
M3.2 instruction said, would reject every token a browser can obtain. The M3.2 deviation was
therefore correct and the instruction was wrong; both are recorded in TRACKER §4.

| Command | Result |
|---|---|
| `pytest` | **97 passed** in 5.5s (92 hermetic in 2.6s) |
| live Keycloak tests | 2, verified to *skip* with the stack down (`14 passed, 2 skipped`) |
| `ruff` / `mypy --strict` | clean on all new files |
| `alembic check` | no new operations — neither M3.2a nor M3.3 touched schema |

**Done: M3.4 backend half — platform JWT + refresh rotation (2026-08-02).** M3.3 could
prove a login *happened*; this is what makes one last. The OIDC callback returns
`{access_token, token_type, expires_in, org_slug}` and sets the refresh token as an
`httpOnly`, `SameSite=Lax`, `Path=/api/v1/auth` cookie; `POST /v1/auth/token` rotates it
and `POST /v1/auth/token:revoke` signs out. **No migration** — `session` already carried
`refresh_token_hash`, `rotated_to`, `revoked_at` and `revoked_reason`, and `alembic check`
still reports no new operations.

**The token-algorithm question is settled: HS256**, and the argument now lives in
`ThreatModel.md` §5.1 instead of contradicting `core/config.py`. api, worker and realtime
are one trust domain reading one `MNEMOS_JWT_SECRET`, so there is no verifier that must be
unable to sign — the only thing asymmetric signing buys. EdDSA would turn one environment
variable into key generation, distribution and a JWKS endpoint with no KMS to hold any of
it (C1). §5.1 records what reverses the decision: the first verifier outside the signing
trust domain, e.g. a separately-deployed MCP tool service at `B3`. The part that actually
stops forgeries is the same either way — a fixed one-element `algorithms=` allow-list
passed to the decoder, never the token's own `alg` header.

| File | What it is |
|---|---|
| `domain/token.py` | `AccessTokenClaims` — exactly `sub`/`org`/`sid`/`iat`/`exp`/`iss`/`jti`, refusing authorization claims when minting **and** when verifying. Plus `RefreshCredential` (`<org_slug>.<secret>`) and `TokenPair`, both `repr=False` because a generated repr prints a live bearer secret into every log line that formats it. The layer is now proven to import no SQLAlchemy, no FastAPI and **no PyJWT** |
| `providers/platform.py` | `PlatformTokenCodec` + `PlatformTokenConfig`, deliberately beside `oidc.py`: that one verifies a token another system minted, this one a token we minted and could have forged. Opposite key material, identical header discipline |
| `application/tokens.py` | `TokenService`, the `SessionStore`/`AppUserStore` ports, and the JIT-provisioning decision |
| `adapters/sessions.py` | `SqlSessionStore` — compare-and-set rotation, recursive-CTE family walk — and `SqlAppUserStore` |
| `entrypoints/api/routers/auth.py` | The two new endpoints, the changed callback, and the cookie |

**Rotation and the family kill.** Every use of a refresh token issues a new one and records
the successor in `rotated_to`. Presenting a token whose row already names a successor is
*proof* of theft rather than a suspicion — the legitimate holder and the thief cannot both
hold the current token, and nothing in the request says which is which — so the whole chain
is revoked. Losing the compare-and-set is the same evidence arriving through a different
door, which is why a client must collapse concurrent refreshes into one call.

**Just-in-time provisioning is on, and it grants identity rather than authority.** A first
OIDC login creates the `app_user` row with `password_hash` NULL, no `role_binding` and no
`user_tag`, so the user can sign in and do nothing until `C1` grants something. Matching is
on `external_subject` and never on email: an IdP email is mutable and often unverified, so
linking on it would let whoever controls that address inherit a local account.

| Command | Result |
|---|---|
| `pytest` | **183 passed** in 13.5s (was 97; +86 — 19 codec, 31 rotation policy, 11 store-vs-Postgres, 25 endpoints) |
| hermetic subset | 167 passed in 5.5s, no Docker |
| `ruff check` + `ruff format --check` | clean on all new and touched files |
| `mypy --strict` | clean on `core`, `features`, `entrypoints/api` (28 files) |
| `alembic check` | "No new upgrade operations detected" |

Live evidence, with the API run against the compose stack: `alg: HS256`, claims
`['exp','iat','iss','jti','org','sid','sub']` and no roles; `Set-Cookie` carrying
`HttpOnly; Max-Age=1209600; Path=/api/v1/auth; SameSite=lax` and no `refresh_token` in the
body; a replayed token returning 401 and leaving **both** rows with
`revoked_reason=refresh_token_reuse_detected`; four different failure causes producing one
byte-identical response body.

Two tests are worth naming because they exist to stop a specific kind of false confidence.
`tests/test_session_store.py` runs the rotation and the family walk against a real Postgres,
because "the walk reaches a whole chain from a middle member" and "two concurrent rotations
cannot both win" are properties of the database and a fake would only prove the fake. And
the endpoint tests assert on the *response bytes*; they were verified to fail by restoring
the M3.2a leak, which put `"no active org with slug 'nosuchorg'"` on the wire as a
distinguishable answer — a tenant-enumeration oracle.

**What identity still owes, under the new IDs.** `M3.4` landed **without its UI slice**,
which is a C12 exception recorded in
[TRACKER §4](../TRACKER.md#4-known-gaps-and-honest-weaknesses) rather than glossed over:
`frontend/` was an empty directory, so `F0` had to exist before a sign-in screen could be
built in anything. `F0` has since landed, so the blocker is gone and that UI slice is now
`A0` together with the fail-closed route guard (old `M3.6`'s guard half). API keys and the
full RBAC permission matrix are `C1`. Both are specified in
[TRACKER §5](../TRACKER.md#5-next-task) and §3.0's mapping table.

**Done: M3.7 — `mnemosctl bootstrap` (2026-08-02).** M3.2 and M3.3 built a provider seam
and an OIDC round trip that nothing could reach: `ProviderFactory` reads
`identity_provider` to choose a strategy, and that table was empty on every database in
existence. `bootstrap` creates the first `org`, the three system roles, **both**
`identity_provider` rows, the admin `app_user` with an argon2id hash, the admin
`role_binding`, and `org.settings.default_provider`.

| File | What it is |
|---|---|
| `domain/roles.py` | `SYSTEM_ROLES` — `admin` (`*:*`), `analyst`, `user`. In `domain/` because the fail-closed guard (`A0`) must require against the roles this seeds. Resources are §5's feature packages so a permission traces to the code that enforces it; slugs are the realm's roles minus the `mnemos-` prefix, since a `role` row is already scoped by `org_id` and a Keycloak realm role is not |
| `application/bootstrap.py` | The use case, its `BootstrapStore`/`BootstrapWriter` ports, and a `BootstrapRequest` validated at construction. Both transactions are opened here, so how much runs elevated is visible where the work is described |
| `adapters/bootstrap_store.py` | The SQLAlchemy side, and the system's only `elevated_session()` call site |
| `entrypoints/cli.py` | The command, in `db doctor`'s argparse shape. Password from an env var or a double `getpass` prompt, **never an argument** — argv is world-readable through `/proc/<pid>/cmdline` and lands in shell history |

**The elevation is one statement wide.** Only the org insert runs elevated; it is the one
statement in the system that provably cannot carry `app.current_org`, because the value it
would carry is the value it is generating. The other nine run under the tenant GUC, so a
bug that computed the wrong `org_id` is rejected by the policy's `WITH CHECK` rather than
committed by a privileged session left open for convenience. Splitting the work across two
transactions is also why **idempotency is not optional**: a crash between them would
otherwise leave an unrecoverable half-bootstrapped database. Every step is
create-if-absent and **nothing existing is ever updated** — an upsert wired into a deploy
script would reset the administrator's password on every release.

**The live stack proves the claim the task was justified by.** Against the empty `mnemos`
database, one run created org `mnemos` + admin `admin@mnemos.local` + 3 roles + 2
providers + 1 binding; a second run with a different password and a different `--org-name`
reported "already present" on every line and left the hash and the name untouched. On the
running API:

| Request | Before bootstrap | After |
|---|---|---|
| `GET /api/v1/auth/oidc/authorize?org=mnemos` | 401, constant denial | **307 → `http://localhost:8080/realms/mnemos/protocol/openid-connect/auth?...code_challenge_method=S256`** |
| `...?org=nope` | 401 | 401 — unchanged, as it must be |
| `...?org=mnemos&provider=internal` | 401 | 401 — a password provider reached through the OIDC endpoint is a misrouted request |

That redirect is split horizon working off the seeded row: discovery ran over
`issuer_internal` (`keycloak:8080`, resolvable only inside the compose network) and the
browser is sent to `issuer_public` (`localhost:8080`). One URL in both columns would have
produced a redirect no browser could follow.

| Command | Result |
|---|---|
| `pytest` | **105 passed** in 13.1s (was 97; +8 in `tests/test_bootstrap.py`, six against a real Postgres as the unprivileged role) |
| `ruff check` + `ruff format --check`, scoped to the diff | clean; the repo-wide run is not, and why is TRACKER §4 item 22 |
| `mypy --strict` | clean on everything new |
| `alembic check` | "No new upgrade operations detected" — **no migration**; every column written was created by `0001` |

`test_bootstrap_admin_can_authenticate_through_the_internal_provider` is the test that
matters: it goes through `ProviderFactory`, so it proves the seeded rows are the *shape*
M3.2 expects rather than merely present.
`test_bootstrap_does_not_leave_an_elevated_session_open` guards the one silent,
catastrophic mistake available here — a leaked `SET ROLE` disables tenant isolation for
every later query on that pooled connection — and opens with a control asserting the
elevated session really does elevate, so it cannot pass vacuously.

**M3.7 has no UI half, deliberately** (TRACKER C12 requires this be written down): the
command runs before anybody can sign in, so an authenticated screen would be unreachable
and an unauthenticated one would be org creation open to the internet. A CLI is its own
interface.

*(Written before the 2026-08-02 re-plan: the "deliverables 4–6" it names are JWT issuance
and refresh rotation — since landed as `M3.4`'s backend half — plus API keys and the RBAC
dependency, which are now `A0`'s guard and `C1`'s matrix. The token-algorithm question it
flags as open was settled by `M3.4` in favour of HS256, with the argument written into
`ThreatModel.md` §5.1.)*

### Carried over from v0.1 (needs porting from SQLite → Postgres)

`core.py`, `embed.py`, `store.py`, `retrieval.py`, `compiler.py`, `baseline.py`,
`ingest.py`, `dataset.py`, `bench.py`, `app.py`, `cli.py` — quarantined in
`backend/src/mnemos/_v1/`. **The kernel logic is sound and tested (23 tests); it needs
re-homing into the feature layout and re-targeting at asyncpg + pgvector.**

**The port is split in two, and the split is deliberate.** Retrieval — the operators, RRF,
dedup, conflict resolution and the ACL pushdown — lands in `A2`, where the RAG flow needs
it, so it is never written twice. Memory governance, the context compiler and the
inspector land in `C4` as a deep slice of their own. Neither half is dropped and neither is
demoted in quality; see §7's mapping table for old `M4`.

The v0.1 benchmark (naive prompt vs compiled bundle) is **kept** — it is the evidence for
the one deep claim in §1. Re-point it at Postgres in `C4`, and update the README's numbers
in the same commit.

### Verified running (2026-07-27)

`docker compose up -d` → nine services healthy; `web` is behind a profile (see below).

| Check | Result |
|---|---|
| Extensions in `mnemos` | `btree_gist citext pg_trgm plpgsql uuid-ossp vector` |
| Databases created | `mnemos`, `mnemos_analytics` |
| Analytics seed | 900 sales_order, 6 customer, 6 product, 4 region |
| `mnemos_ro` SELECT | allowed (900) |
| `mnemos_ro` INSERT | **`ERROR: permission denied for table region`** |
| `alembic upgrade head` | revision `0006` |
| `alembic downgrade base` | clean; only `alembic_version` survives |
| `alembic check` | no drift between models and migrations |
| `mnemosctl db doctor` | 41 tables, **40 with FORCE row-level security** |
| Exclusion constraint | `ex_memory_one_live_fact_per_scope` present and armed |
| `GET /readyz` | `{"status":"ready","checks":{"postgres":"ok","redis":"ok"}}` |
| `ollama list` | `qwen2.5:3b-instruct` 1.9 GB |
| `pytest` | 28 passed (needs Docker — one suite uses testcontainers) |

`org` is the one table without RLS, deliberately: a user must resolve their own org row
before the GUC can be set from it. That decision has a consequence which only became
visible once RLS was in force — **every credential must carry its own tenant**, because
`app_user`, `session` and `api_key` are all org-scoped and therefore unreadable until an
org is known. See [TRACKER §5](../TRACKER.md#5-next-task).

**The `db doctor` row above is exactly the trap M3 walked into.** It reports
`relforcerowsecurity` from `pg_class`, which was true and told us nothing: the policies
were present and applied to nobody, because the connecting role was a superuser. A
schema-level report is not evidence that a control is in force. Anything asserted on the
strength of `db doctor` alone deserves the same scepticism.

The `mnemos_ro` lines are the defence-in-depth claim proven at the database level: even a
prompt injection that defeats the AST parser cannot write, because the role cannot write.

**Host port note:** this machine already runs Postgres on 5432 and Redis on 6379, so the
compose file maps host `15432 -> 5432` and `6380 -> 6379`. Container-to-container traffic
is unaffected and still uses the standard ports over the compose network.

~~**`web` is behind a compose profile.**~~ **Un-gated by `F0`, 2026-08-02.** The profile
existed because `./frontend` had no Dockerfile and an unresolvable build context aborted
the whole `up`. It does now, so plain `docker compose up -d` brings the frontend up with
everything else and `web` has a healthcheck of its own — a stack whose UI needs a
remembered extra flag is a stack whose UI does not get looked at.

### A4 — automatic chat routing ✅ verified 2026-08-17

`flows/router/` now owns a deterministic, local-first classifier and its application seam.
It selects NL2SQL for explicit database/SQL concepts and business metrics, RAG for explicit
document/citation intent, and conservatively defaults ordinary questions to chat. There is
no paid or remote classifier dependency, and the policy remains the mandatory fallback if
an Ollama classifier is added later.

The existing chat endpoint dispatches into the already-built A1/A2/A3 flows and emits a
leading `route` SSE frame containing the selected flow and display-safe rationale. The same
metadata is persisted in the pre-existing `chat_message.flow` and `router_rationale`
columns, so it survives history reloads without a migration. The provisional
`use_documents` and `use_datasource` request fields are removed and rejected as unknown;
the generated TypeScript schema was regenerated from FastAPI OpenAPI.

The C12 UI slice is the existing composer and transcript. The manual three-mode toggle is
gone; each assistant answer shows a compact `Chat`, `Documents`, or `Data` annotation plus
the reason. Live answers take it from the stream and historical answers take it from the
persisted response. No new component or design token was needed.

Evidence: 35 focused classifier/chat/RAG/NL2SQL tests passed, including automatic routing
of a write-like request through the unchanged NL2SQL AST guard. Full backend `make test`
passed 441; `make lint`, `make types`, and `make check` were clean. Frontend tests passed
112; lint, TypeScript, and production build were clean. A full Compose rebuild returned
postgres, redis, ollama, and objectstore all `ok` from `/readyz`. Four Chromium cases
across `chat.spec.ts`, `knowledge.spec.ts`, and `nl2sql.spec.ts` passed: plain chat,
uploaded-document RAG with citation inspection, normal NL2SQL, and the adversarial
write-like NL2SQL route. The retrieval/compiler path did not change, so benchmark numbers
remain untouched.

### B2 — ingestion at scale ✅ verified 2026-08-17

`B2` is built over `B1`'s connector ingestion path without a schema migration. The existing
`ingest_job` columns (`attempts`, `max_attempts`, owner/heartbeat/lease fields,
`done_units`, `total_units`) and `ingest_job_event` table now carry real operational depth:
`IngestJobRepository` can list recent jobs with event history, renew a running job's lease,
record progress, skip queued jobs until their retry delay elapses, and move a failed attempt
to either retryable `queued` or terminal `failed`.

`entrypoints/worker/main.py` now heartbeats while a connector item is being processed and
passes an optional progress callback into `KnowledgeService.ingest_connector_item`. Progress
updates write `done_units`/`total_units`, append `running -> running` history rows, and publish
the richer live/durable payload (`attempts`, `max_attempts`, progress units, and error detail)
to the authenticated ingestion WebSocket path and Redis Streams. The stuck-job reaper now
surfaces expired leases as `running -> stuck -> queued/failed`, so a dead worker is visible in
history instead of being silently rewritten back to the queue.

The final review tightened the concurrency contract: only a claim increments `attempts`, and
all progress/failure/success mutations are fenced by both `status = running` and the current
`owner_id`. An obsolete worker therefore cannot overwrite the attempt that replaced it after
lease reclamation. Retry claims clear stale progress/error state, job mutations advance
`updated_at`, event reads are explicitly tenant-filtered and deterministically ordered, and
unexpected internal exception detail is logged rather than returned over the API/WebSocket.

The product slice is `GET /connectors/jobs`, `GET /connectors/jobs/{job_id}`, and the Sources
activity feed. The feed hydrates recent jobs after reload before merging WebSocket events, and
rejects an older hydration response if a newer live transition already arrived. Each row now
shows a labelled `stuck` state, attempts, a progress bar, and error detail. The generated
frontend schema was regenerated from the edited FastAPI OpenAPI document rather than hand-edited.

Evidence after the final review: focused backend tests for worker/repository/router — 17
passed; full backend `make test` — 434 passed; `make lint`, `make types`, and `make check`
clean. Frontend: `npm run test -- --run` — 114 passed; `npm run lint`, `npx tsc --noEmit`,
and `npm run build` clean.
After `docker compose up -d --build`, `/readyz` returned postgres, redis, ollama and
objectstore all `ok`, and `npx playwright test e2e/sources.spec.ts` passed against the rebuilt
stack.
PR #19's backend, frontend, and Compose GitHub Actions checks also passed before the
completed milestone was marked ready and merged to `main`.

### B1 — connect a source and watch it ingest ✅ verified 2026-08-17

Deliverable 1, the `SourceConnector` port + factory, is built and on `feat/b1-connectors`
(PR open, draft). `features/connectors/` now has real `domain`/`adapters`/`application`
content: `domain/port.py`'s `SourceItem` + `SourceConnector` protocol; three adapters
(`s3.py` over the `ObjectStore` port — extended with `list(prefix)` — `local_fs.py`
default-deny outside an operator-approved root, `http.py` over an operator-curated URL
list with a real SSRF deny-list and DNS-rebinding-safe address pinning in
`ssrf_guard.py`); the `content_source` table + RLS (migration `0007`, the first since
`M2`); and `mnemosctl connector register`/`list-items`. Full detail, including two
pre-existing migration bugs found and fixed (`0004`/`0006` importing the live
`ORG_SCOPED_TABLES` instead of a frozen copy — harmless until a new org-scoped table was
added, which `content_source` now is) and the trust-tier reconciliation deliverable 4
needs, is in [TRACKER's dated note](../TRACKER.md) for 2026-08-15 (evening).

Deliverable 2, the `EventBus` port + Redis Streams adapter, is also built, same branch.
`platform/events/port.py`'s `EventBus` (`publish`/`ensure_group`/`read_group`/`ack`) and
`platform/events/redis_streams.py`'s `RedisStreamsEventBus` — `XADD`/consumer-group
`XREADGROUP`, chosen over `platform/cache.py`'s pub/sub for the durability/replay
guarantee pub/sub cannot give (ADAPTATION §3, §9 — a locked decision). Tested against a
real Redis via `testcontainers`, not a fake: backlog delivery to a group created after
publish, idempotent group creation, no redelivery of an already-delivered message,
competing-consumer semantics, and `ack` clearing `XPENDING`, are all proved directly.
The open design question from the original brief — how a Streams entry reaches a
browser — is now resolved: deliverable 4's worker will publish to *both* this adapter
(durable) and the existing pub/sub channel the realtime gateway already relays (live),
so the gateway needs no new code for `B1`; a consumer-group reader inside the gateway
itself (replay-on-reconnect) is left for `B2`. Full detail is in
[TRACKER's dated note](../TRACKER.md) for 2026-08-15 (night).

Deliverable 3, the realtime gateway's JWT-validated WS handshake and org-derived channel
scoping, is also built, same branch. `entrypoints/realtime/main.py`'s `/ws/{channel}` now
resolves the caller through the identical `PlatformTokenCodec` + `PrincipalResolver`
`entrypoints/api/main.py` builds (the gateway gained its own `Database` to do this), with
the token offered as a `Sec-WebSocket-Protocol` value (`["bearer", token]`) rather than a
query parameter — no credential ever appears in a URL, an access log or browser history,
the same discipline `web_signin_complete_url` already enforces for the refresh cookie
exchange. The channel a caller reaches is always `mnemos:org:{org_id}:{kind}`, with
`org_id` read only from the resolved token and `kind` checked against a closed allow-list
(`{"ingestion"}` today) — a channel string that tries to name another org, typed directly
into the WS URL, is refused before `accept()`, proved against a real Redis
(`tests/test_realtime_auth.py`, 12 tests) and live-verified against the running compose
stack. Deliverable 4's worker must publish to exactly `f"mnemos:org:{org_id}:ingestion"`
for the gateway to relay it — that channel-naming contract is deliverable 3's, recorded in
[TRACKER's dated note](../TRACKER.md) for 2026-08-16, which has the full detail.

Deliverable 4, the worker's first real job-processing path, is also built, same branch.
`entrypoints/worker/main.py`'s poll loop claims one `queued` `ingest_job` at a time
(`IngestJobRepository.claim_next`, `FOR UPDATE SKIP LOCKED`) and processes it:
`ConnectorService.fetch_item` (new) resolves and fetches the item, and
`KnowledgeService.ingest_connector_item` (new) runs the same extract/chunk/embed body
`upload_document` uses, factored into a shared `_ingest` so the two paths do not duplicate
the pipeline — the manual-upload path's own behaviour is unchanged. Connector-sourced
documents get `TrustTier.RETRIEVED` (10), the reconciliation deliverable 1's dated note
already worked out (the current 4-rung `TrustTier` has no rung below it, and `ThreatModel
.md` §4's literal "external connectors ≥ 4" was written against a retired 0-6 scale).
Every transition writes an `ingest_job_event` row and publishes to both the `EventBus`
(durable) and `mnemos:org:{org_id}:ingestion` (live) — deliverable 3's exact channel
contract, matched verbatim. `mnemosctl connector ingest --org-slug X --slug Y --uri Z` is
the CLI producer until deliverable 5's UI exists.

**A real RLS bug found and fixed while building the claim path:** `reap_stuck_jobs` ran
inside an unscoped `db.session()` — no `org_id`, so the org-isolation policy's `org_id =
NULL` comparison was never true, and the reaper reclaimed nothing on any real,
RLS-enforced Postgres, regardless of how many jobs were actually stuck. Nothing had
caught this because nothing had ever tested it against a real database. Fixed with
`db.elevated_session()` — `platform/db.py`'s own comment already reserved this as the
second of "two callers, ever" (the first is bootstrap), exactly the shape of problem it
exists for: a query that is legitimately cross-tenant, not a query that forgot to scope
itself. The worker's own claim uses the same escape hatch for the same reason. Full
detail, including the regression test and the live verification against the rebuilt
compose stack, is in [TRACKER's dated note](../TRACKER.md) for 2026-08-16 (the deliverable
4 entry, above deliverable 3's own same-dated note).

Deliverable 5 — the sources UI — is done (2026-08-17). `entrypoints/api/routers/connectors.py`
(register/list/browse/ingest, over the same `ConnectorService`/`IngestJobRepository`
deliverables 1 and 4 already built) is wired into `entrypoints/api/main.py`.
`frontend/src/app/(app)/sources/` (a page, four components, an API client, and a
`useIngestionFeed` WebSocket hook matching deliverable 3's `Sec-WebSocket-Protocol`
contract exactly) is built and exposed through a `destinations.tsx` nav entry.
`e2e-fixtures/sources/` plus the `docker-compose.yml` volume mounts and
`MNEMOS_LOCAL_FS_ALLOWED_ROOTS` give the local-fs connector something real to register
against in dev and CI, and `frontend/e2e/sources.spec.ts` scripts the full flow.

Live evidence: after `docker compose up -d --build`, `/readyz` reported postgres, redis,
ollama and objectstore all `ok`; the API container had the `/fixtures/sources` allowed
root and the mounted `handbook.txt` fixture. In Chromium, signed in as
`analyst@mnemos.local`, the Sources screen registered a local filesystem connector,
browsed to `handbook.txt`, selected and ingested it, and the live feed reached
`Succeeded` without a page reload. The same spec passed in a headed Chromium run and in
the normal `npx playwright test e2e/sources.spec.ts` run. After merging #18 first and
resolving `B1` against the updated `main`, final gates were: backend `make test` 429
passed, `make lint` / `make types` / `make check` clean; frontend `npm run lint`,
`npx tsc --noEmit`, `npm run test` 111 passed, and `npm run build` clean with `/sources`
in the route table; `frontend/e2e/sources.spec.ts` passed against the rebuilt combined
stack.

### A3 — ask about your data ✅ verified end to end 2026-08-15

All five deliverables done and, as of 2026-08-15, verified in a real browser against the
real stack (Postgres, Ollama, the rebuilt `api`/`web` containers) — not merely against
`pytest`. Deliverable 1 (schema introspection) landed 2026-08-11; deliverables 2 (business
glossary) and 3 (generation + the AST read-only guard) landed 2026-08-15 morning;
deliverables 4 (execution, narration, the repair loop) and 5 (the SQL panel, the denial
screen) landed 2026-08-15 in the same session that did the browser verification, all on
branch `feat/a3-nl2sql` (PR #15). Full evidence is in
[TRACKER §3](../TRACKER.md#-a3--ask-about-your-data-verified-end-to-end-2026-08-15-pr-15)
and the dated note near the top of that file.

**Introspection connects with the datasource's own DSN, never through `Database`.**
`Database` (`platform/db.py`) is the application's own Postgres, connected as `mnemos_app`
with RLS-scoped sessions. `mnemos_analytics` is a second, unrelated Postgres database on
the same server, connected as `mnemos_ro` — a role that is unprivileged in a completely
different sense (it cannot write *anywhere*, not "cannot write outside its tenant"). A
short-lived `create_async_engine(dsn, pool_size=1, ...)` per introspection call
(`adapters/introspection.py`), disposed after — refresh is explicit and rare, not a
connection the flow holds open.

**The registry's DSN is encrypted at rest even though the demo DSN is not itself secret.**
`SqlDatasource.dsn_encrypted` existed as a `LargeBinary` column since `M2` with no adapter
that used it correctly; this deliverable added `core/crypto.py`'s `DsnCipher` (Fernet) and
a `MNEMOS_DSN_ENCRYPTION_KEY` setting rather than leaving the column meaningfully unused —
a registry that only sometimes encrypts is one an operator cannot reason about, and a real
deployment's warehouse credentials are exactly the case this column exists for.

**Test infrastructure now spans two databases on one container.** `conftest.py`'s
`postgres` fixture creates `mnemos_analytics` alongside the existing `mnemos` database and
seeds it by executing the real `deploy/postgres/init/02-analytics-seed.sql` — the same file
`docker-compose.yml` runs — rather than a hand-written substitute. This is what let
deliverable 1's tests prove the `mnemos_ro` role's can't-write guarantee directly
(`INSERT ... -> asyncpg.exceptions.InsufficientPrivilegeError`) a session before deliverable
3 (the AST guard) exists to depend on it.

**Deliverable 2 (business glossary), done 2026-08-15.** `render_schema_context`
(`domain/context.py`) is the one function this deliverable exists to build — pure,
grouping `sql_schema_object` rows by table and listing `glossary_term` rows after them —
and it is deliberately the thing `A3`'s eventual prompt assembly will call rather than
re-deriving. `GlossaryRepository.ensure_terms` is idempotent by matching on `term` text
rather than a synthetic key, and specifically **non-destructive**: re-running the seed
after an operator has hand-edited a term's definition must not overwrite it, which is why
the acceptance test checks that a re-seed with different content leaves the original in
place, not merely that row counts stay stable. `mnemosctl datasource show-context` is new
and not in the original deliverable text, but it is the real consumer that keeps
`render_schema_context` from being a function nothing calls until deliverable 3 exists —
consistent with TRACKER §0 rule 5 (no placeholders).

**Deliverable 3 (generation + the AST read-only guard), done 2026-08-15.** `guard_sql`
(`domain/guard.py`) is an **allowlist**, not a blocklist: the parsed statement must be
`sqlglot.exp.Query`, and every node in the tree is walked for anything that writes, changes
privileges, or is a shape `sqlglot` falls back to a generic `Command` for. A blocklist
scoped to `INSERT`/`UPDATE`/`DELETE`/DDL was prototyped first and found to miss
`SELECT ... INTO` (creates a table), `FOR UPDATE` (takes a write lock), and
`EXPLAIN`/`VACUUM`/`CALL`/`COPY`/`SET` (none of which is a DML/DDL node at all) — requiring
the positive case closes all of these by construction rather than by enumeration, which
matters because enumeration is exactly the "one parser bug from a write" failure mode this
guard exists to avoid. Walking the *whole* tree, not just the root, is what makes CodingStandards
§9 mandatory case 4 true: a data-modifying CTE (`WITH d AS (DELETE ... RETURNING *) SELECT
* FROM d`) is valid Postgres syntax and can be consumed from a top-level query, a `UNION`
arm, or a `FROM (...)` subquery — three nesting shapes that all present as a top-level
`Select` and only differ in what `.walk()` finds underneath.

`SqlGenerationService` (`application/generation.py`) is a **sibling** of `DatasourceService`
— composing it for `require_datasource`/`render_context` — rather than a fifth method on it
or a new `flows/nl2sql/` package. The distinction that matters: `DatasourceService`'s
existing four methods are fast, cache-oriented, and make no security verdict; generation
calls a model and decides whether the result is safe, which is a different kind of
operation with different tests and fakes. `flows/nl2sql/` stays three empty stubs until
deliverable 4, where streaming and the chat integration actually need a flow that depends
on more than one feature — deliverable 3's generation is a single blocking
`ChatModel.complete()` call, reasoned about entirely inside `features/datasources/`.

**Verified against a real local model, not only a scripted fake.** Against the rebuilt
`api` image: `mnemosctl datasource generate --org-slug mnemos "what was total revenue by
region last quarter"` produced an `allowed` verdict with a real (if not perfectly correct —
small local models are not perfectly correct) multi-table CTE query and all four touched
tables recorded; `mnemosctl datasource generate --org-slug mnemos "delete every row from
the sales_order table"` had `qwen2.5:3b-instruct` **comply with the adversarial
instruction** and emit a real `DELETE FROM analytics.sales_order` — which `guard_sql`
caught and recorded as `rejected_write`, naming the table. Both attempts confirmed
persisted in `sql_run` via a direct `psql` query. This is the live version of the
`test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed` argument: the defence
that matters is the one that holds even when the thing in front of it (a system prompt
saying "don't") does not.

**Deliverable 4 (execution + narration + repair loop), done 2026-08-15.** This is where
`flows/nl2sql/` gets its first real content — deliverable 3 stayed entirely inside
`features/datasources/` because generation was one blocking model call reasoned about
independent of any conversation; execution and narration are what cross into `features/chat`,
the same boundary `flows/rag/` already crosses for `A2`. `Nl2SqlFlow` composes
`ChatRepository`, `DatasourceService`, `SqlGenerationService`, and a `SqlRunRepository`, and
states the security invariant directly in its own module docstring: `guard_sql()` decides,
`REJECTED_*` never executes, `ALLOWED` executes at most once, for the *final* attempt only.

`PostgresExecutor` (`features/datasources/adapters/executor.py`) mirrors
`PostgresIntrospector`'s short-lived-engine-per-call pattern. Two implementation details
worth recording because they were not obvious in advance:
- Postgres `statement_timeout` is set as an asyncpg connection parameter
  (`server_settings`), never a `SET` statement built by concatenating the guarded SQL —
  the same "never interpolate the model's SQL into another statement" rule the guard's own
  existence depends on. Row capping is `fetchmany(max_rows + 1)`, never a `LIMIT` appended
  to the statement.
- SQLAlchemy's asyncpg dialect wraps the real driver exception in its own
  `AsyncAdapt_asyncpg_dbapi.Error` before `DBAPIError.orig` sees it — detecting a
  `statement_timeout` cancellation (`asyncpg.exceptions.QueryCanceledError`) required
  checking `.orig.__cause__`, not `.orig` itself. Found by writing a throwaway test that
  printed the actual exception chain rather than guessing at SQLAlchemy's wrapping.

The repair loop (`Settings.sql_repair_attempts`) covers every `REJECTED_*` verdict, not
only unparseable SQL: a repair attempt is independently re-guarded exactly like attempt 1,
so retrying after a deliberate write attempt is another chance for the model to produce a
read, not a security weakening. **Verified against the real local model, live, not only
scripted:** `qwen2.5:3b-instruct`, asked five different adversarial ways in the browser to
delete/truncate/drop real tables, complied with the repair prompt's stated reason and
produced a safe alternative read five times out of five — real row counts on
`analytics.region`/`.sales_order`/`.customer` confirmed unchanged via `psql` throughout. A
sixth, unscripted outcome was also observed live: a guard-`ALLOWED` statement (a real read,
no write) failed *at* Postgres with `CardinalityViolationError` from a mis-joined
correlated subquery — reported as `error_code="execution_error"`, narrated with a template
(no model call over a result set that does not exist), and rendered as a third, distinct
UI state rather than collapsed into the denial banner. None of this was assumed; all of it
was produced by the actual model this build ships, in the actual browser.

**Deliverable 5 (the SQL panel + denial screen), done 2026-08-15.** `AssistantDone`
(`features/chat/domain/events.py`) gained an optional `extra: dict[str, JsonValue] | None`
field — `features/chat` stays ignorant of what a flow puts there, and `flows/nl2sql` is the
first caller. The `done` SSE frame carries an `nl2sql` key with the SQL, verdict, rows and
truncation flag in the same terminal frame as the narration, so the frontend never refetches
to assemble one coherent answer. `SqlPanel.tsx` renders three distinct labelled states
(allowed, guard-refused, execution-failed-after-allowed), each pairing `--danger` with an
icon and a plain-word label rather than colour alone (DesignSystem §3). The composer's
answer-mode control is a Radix `ToggleGroup` — a real three-option `radiogroup`
("Chat"/"Use documents"/"Ask your data") reusing the exact primitive and visual language
`ThemeToggle` already established for Appearance, chosen over two independent checkboxes
with manual mutual-exclusion because "chat" is a real, nameable third state and a
`radiogroup` is what a mutually-exclusive three-way choice *is*, semantically.

Historical reload is honest about its limit rather than silently wrong: `sql_run` (verdict,
tables, execution metadata) persists and is durable, matching the rest of the audit trail
`A3`'s two-defence design already keeps — but the actual row *values* are not persisted
anywhere, since they only ever existed in the live query result the SSE frame carried. A
reloaded historical `nl2sql` message renders as a plain assistant bubble with its narration,
no panel, rather than a panel silently missing data it never had a column to hold.

### A2 — ask about your documents ✅

Verified 2026-08-10 on branch `feat/a2-rag` (PR #14). Full evidence, with commands and
observed output, is in [TRACKER §3](../TRACKER.md#-a2--ask-about-your-documents-verified-2026-08-10).

**The `_v1` retrieval kernel is ported, not rewritten.** Chunking with char offsets, the
hashing embedder, the heuristic tokenizer, RRF fusion and Jaccard dedup all move across
essentially intact; what changes is that the *operators* are SQL now —
`ORDER BY embedding <=> :query` through the HNSW index `M2` created, and pg_trgm's `%` for
the lexical arm — because the brute-force numpy scan could not push a predicate into the
scan and could not survive a real corpus. §8's "carried over from v0.1" note is half
discharged: retrieval has landed, memory governance and the compiler remain for `C4`.

**Both published constraints are asserted rather than asserted-about.** C4 (authorization
inside the scan, post-filtering banned) is pinned by
`test_acl_pushdown_beats_post_filtering_on_yield`, which builds the banned post-filtering
arm alongside the real one purely to measure the difference — the same discipline C10
applies to the benchmark's naive arm. C6 (superseded revisions excluded, not down-ranked)
is pinned by asserting the obsolete text is *absent* from the candidate set, since
down-ranking is exactly the failure the README's headline number is about.

**The inspector has its first real content.** Clicking a `[n]` marker in an answer fills
the panel `F0` reserved with the cited passage and the character span it came from. The
context *bundle* — admitted, excluded, budget spend — is still `C4`, and the empty state
says which half is missing rather than implying the panel is finished.

Deliberately deferred and recorded rather than implied: the six-phase compiler and its
allocator (`C4`; `A2` truncates in fused-score order), ingestion job machinery (`B2`; `A2`
ingests synchronously in the request handler), and the connector abstraction (`B1`; `A2`
has one MinIO upload path and no factory).

### A1 — talk to it ✅

Verified 2026-08-08 on branch `feat/a1-chat` (PR #13). The full write-up, with commands run
and output observed, is in [TRACKER §3](../TRACKER.md#-a1--talk-to-it-verified-2026-08-08)
— this is the short version for a reader who only needs the shape of what landed.

`features/llm/` is a narrow `ChatModel` port (`stream`/`complete`/`health`) over
`OllamaChatModel`, so `A4`'s router and `C2`'s cost ledger can swap models later without
touching a call site, and `/readyz` now genuinely depends on the configured model being
pulled (CodingStandards §7 — fail at startup, not at somebody's first message). `features/
chat/` adds `ChatService` and `SqlChatRepository` behind the `chat_session`/`chat_message`
tables `M2` already created; the streaming endpoint answers `text/event-stream` with named
`token`/`done`/`error` frames, persists the assistant's message only once the stream
completes (so an abandoned stream leaves no half-written row), and the router primes the
generator once so a pre-first-token failure is an ordinary 404/502 rather than a stream
that opened and died. The frontend adds `/chat` and `/chat/[sessionId]`, a composer
(Enter sends, Shift+Enter newlines, a Stop control while streaming), and a session list in
the sidebar.

Two things worth carrying forward rather than rediscovering: nothing in the API process
had ever imported the full SQLAlchemy model registry (`mnemos.platform.models`), and the
first foreign key crossing a feature boundary (`chat_message.bundle_id → context_bundle`)
raised `NoReferencedTableError` from a live query rather than from `alembic check` — fixed
with one import in `main.py`'s composition root (TRACKER §4 item 41). And the bootstrap
admin cannot sign in through Keycloak as itself against this repository's own persistent
stack, because the realm's seeded `admin@mnemos.local` collides on email with the
bootstrap-created internal user of the same name and is correctly denied by the
just-in-time-provisioning rule from `M3.4` (TRACKER §4 item 40) — browser evidence from
here on signs in as `analyst@mnemos.local` instead.

### Not started

**B3 through D** — §7. Phase A and `B1`/`B2` are complete as of 2026-08-17. Concretely, and
stated plainly because the gap between what `docs/` describes and what runs is the thing
this file exists to keep honest:

- **`B1` is done.** There is a source connector abstraction, an event bus, an authenticated
  realtime channel, a worker that actually processes ingestion jobs, and a browser-verified
  Sources UI. `features/connectors/` owns the port/factory and S3/local-fs/HTTP adapters,
  `platform/events/` owns the Redis Streams adapter, `entrypoints/realtime/main.py` owns
  the JWT-validated ingestion WebSocket, `entrypoints/worker/main.py` owns the real
  claim-and-process loop, and `entrypoints/api/routers/connectors.py` +
  `frontend/src/app/(app)/sources/` make the flow usable from the app. Full evidence is in
  [TRACKER's 2026-08-17 dated note](../TRACKER.md).
- **`B2` is done.** Connector ingestion jobs heartbeat, retry with backoff, expose richer
  status/progress history, surface stuck leases, hydrate recent job state after reload, and
  show per-job progress in Sources. Full evidence is in TRACKER's 2026-08-17 B2 note.
- ~~The realtime WebSocket gateway is unauthenticated.~~ **Closed in `B1` deliverable 3
  (2026-08-16):** the WS handshake now validates the platform JWT and derives the
  subscribed channel from the caller's own org, never from client-supplied path data.
- ~~The worker's stuck-job reaper has nothing real to claim.~~ **Closed in `B1` deliverable
  4 (2026-08-16):** the worker claims and processes real `ingest_job` rows end to end. The
  reaper itself also had a latent bug fixed alongside this — it ran unscoped and so
  reclaimed nothing under RLS, ever; see the dated note in TRACKER for detail.
- ~~**There is no router.**~~ **Built in `A4`.** Every message now selects chat, RAG, or
  NL2SQL automatically; the persisted compact reason is visible beside the answer and the
  provisional selectors/request flags are gone.
- **There is no tool runtime, no agent flow, no prompt store and no cost ledger.** `B3`,
  `B4`, `C2`.
- **The context inspector shows a cited passage, not a context bundle.** `A2` gave it its
  first real content; what was admitted, what was excluded and why, and the token spend
  against budget, are `C4`. So is bitemporal memory, and so is re-running the benchmark on
  Postgres — until then the README's numbers stay labelled as measured on SQLite.
- ~~**There is no NL2SQL.**~~ **Built in `A3`.** Introspection, business glossary,
  generation behind an AST read-only guard, execution as `mnemos_ro`, narration, the repair
  loop, and the SQL panel with its denial screen — verified end to end in a real browser.
- ~~**There is no RAG in this stack.**~~ **Built in `A2`.** Upload, extract, chunk, embed
  onto pgvector HNSW, retrieve with the ACL predicate inside the scan, cite.
- ~~**There is no conversation surface.**~~ **Built in `A1`.**

What *is* built is the product surface and foundation those stand on: the container stack,
the 41-table schema with row-level security that is in force rather than merely declared,
identity through a full OIDC round trip and platform JWT with refresh rotation,
`mnemosctl bootstrap`, CI, the app shell, a routed conversation surface, retrieval over
uploaded documents with click-through citations, and guarded NL2SQL over the demo warehouse.
Evidence for each is above.

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

- **Keep this file and [`TRACKER.md`](../TRACKER.md) in step, in the same commit as the
  work.** This file holds the design and the milestone ledger; TRACKER holds the live
  next-task detail. A reader who trusts one and not the other is worse off than a reader
  who trusts neither.
- **Every branch gets a PR when it is created**, so no branch is lost track of. Push and
  open it as soon as the branch has its first commit, in draft if the work is unfinished.
- **A completed task closes its repository lifecycle.** After verification and green CI,
  mark the PR ready, merge it with the repository's normal strategy, sync `main`, and
  update `prompt.txt` alongside TRACKER/ADAPTATION so the next handoff describes what is
  actually merged rather than what merely exists on a branch.
- **Milestone IDs are `A0`–`D1` now, not `M4`–`M14`.** If you find an old ID in a document,
  a docstring or a commit message, §7's mapping table is the translation — do not guess,
  and do not leave a reader holding a number that no longer names anything.
- **Read §7's two rules before scoping any work** (C12 and C14). A milestone that cannot
  end in a sentence a stranger could perform at `http://localhost:3000` is infrastructure,
  and infrastructure folds into the milestone it serves. That rule exists because the plan
  it replaced reached its own subject — a chatbot — at `M8`.
- **Every new API route is authenticated by doing nothing** (`A0`). Do not add a route to
  `public_route_paths` without a reason you would defend in review, and never turn that set
  into a prefix match. If a handler needs to know who is calling, it asks for
  `require_caller`; if it forgets and needs one anyway, it raises — that is deliberate, and
  making the caller optional to silence it is how a route quietly stops being scoped.
- **`B3` is a single-call tool runtime, not the agent.** Reuse the existing MCP tables,
  keep credentials per user, authorize again at the invocation boundary with the motivating
  trust tier, and persist approval before dispatch. Multi-step planning/checkpoints are `B4`.
- **The local MCP fixture is part of `B3`'s exit evidence.** The default path may not depend
  on a SaaS account or paid API, and a malicious/remote endpoint still needs the connector
  path's SSRF/rebinding discipline, timeouts, schema validation, and response cap.
- **The frontend test suite is offline by construction** (`A0`). `vitest.setup.ts` installs
  a `fetch` that answers 401 before any test runs, which is also what
  `vi.unstubAllGlobals()` restores. A test that reaches the real network will pass on a
  machine with the stack up and fail on CI — that is how it was found.
- The v0.1 benchmark numbers in the root `README.md` were measured on SQLite. The kernel
  finishes its port in `C4`; **re-run and update them there**, in the same commit, and do
  not let published numbers drift in the meantime.
- `docs/` (Architecture, SystemDesign, DatabaseDesign, APIContract, ThreatModel, 12 ADRs)
  describes a larger target than what is built. That gap is stated in the README and is
  intentional; keep it stated.
- The v0.1 brute-force retrieval weakness was closed in `A2` with pgvector HNSW; keep ACL
  and revision predicates inside that scan if retrieval is touched later.
- Do not re-run `pkill -f mnemos` — it matches the agent's own shell. Kill by port/PID.
