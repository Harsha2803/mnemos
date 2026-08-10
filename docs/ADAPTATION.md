# Mnemos — Build Plan & Architecture

> **Read this first if you are resuming work.** It is the authoritative plan and is
> self-contained: architecture, the capability inventory, schema, milestones, and current
> state. [`TRACKER.md`](../TRACKER.md) holds live task status; this holds the design.

**Last updated:** 2026-08-10 — `A2` shipped (ask about your documents: upload, extract,
chunk, embed onto pgvector, retrieve with the ACL predicate in the scan, cite); `A3` is next

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
| **A3** | NL2SQL: introspection · glossary · generate · AST read-only guard · `mnemos_ro` execution · narration · SQL panel | **ask a question about your data in English** and see the SQL, the rows and the narration — and see the guard visibly refuse a write | ⬜ **next** |
| **A4** | Router: classify a message → chat / RAG / NL2SQL · flow indicator | **ask anything without choosing a mode**, and see which flow answered and why | ⬜ |

**At the end of Phase A the thing this project is for exists.** Everything after deepens it.

**Phase B — make it a platform.**

| ID | What it builds | You can now… | Status |
|---|---|---|---|
| **B1** | Object storage · source connectors (MinIO/S3, local FS, HTTP) · Redis Streams event bus · sources UI | **connect a source, browse it, and watch ingestion events arrive live** | ⬜ |
| **B2** | Ingestion jobs at scale: heartbeat, retries, status history, stuck-job reaper · per-job progress UI | **ingest a folder and watch every job's progress — including one that dies, surfaced as stuck rather than silently lost** | ⬜ |
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

**Current position.** `main`'s tip has `A0` (PR #11), `A1` (PR #13) and `A2` (PR #14) — all
merged. `docker compose up -d` brings up nine services with upload → ask → cite working end
to end; verified against the merged image, not just the branch, via the real
`frontend/e2e/knowledge.spec.ts` Playwright suite.

**The next task is `A3`** — natural language over the `mnemos_analytics` warehouse:
introspection, a business glossary, generated SQL behind **two independent read-only
defences** (an AST guard and the `mnemos_ro` role), execution, and narration, fully
specified in [TRACKER §5](../TRACKER.md#5-next-task). The router that stops the user having
to choose a flow is `A4`.

`M3`'s exit criterion "RLS blocks cross-org" turned out to be unmet by `M2` rather than
merely untested; that is written up in §8 and in
[TRACKER §3](../TRACKER.md#3-current-state--what-is-actually-built).

---

## 8. Current state

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

**Phase A3 onward, and all of B, C and D** — §7. Concretely, and stated plainly because the
gap between what `docs/` describes and what runs is the thing this file exists to keep
honest:

- **There is no NL2SQL.** The `mnemos_analytics` warehouse is seeded and the `mnemos_ro`
  role is proven read-only (below), but nothing generates SQL against them. `A3`, and it
  is next.
- **There is no router.** A person still has to tick "Use documents" to get a grounded
  answer; nothing classifies a message to a flow on its own. `A4` — and both provisional
  selectors are written down as provisional so `A4` knows what to remove.
- **There is no tool runtime, no agent flow, no prompt store and no cost ledger.** `B3`,
  `B4`, `C2`.
- **The context inspector shows a cited passage, not a context bundle.** `A2` gave it its
  first real content; what was admitted, what was excluded and why, and the token spend
  against budget, are `C4`. So is bitemporal memory, and so is re-running the benchmark on
  Postgres — until then the README's numbers stay labelled as measured on SQLite.
- ~~**There is no RAG in this stack.**~~ **Built in `A2`.** Upload, extract, chunk, embed
  onto pgvector HNSW, retrieve with the ACL predicate inside the scan, cite.
- ~~**There is no conversation surface.**~~ **Built in `A1`.**

What *is* built is the foundation those stand on: the container stack, the 41-table schema
with row-level security that is in force rather than merely declared, identity through a
full OIDC round trip and platform JWT with refresh rotation, `mnemosctl bootstrap`, CI, the
app shell, a working conversation surface, and retrieval over uploaded documents with
click-through citations. Evidence for each is above.

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
- Known weakness carried from v0.1: brute-force cosine over all chunks per query. Fine at
  demo scale, must become a pgvector HNSW index query in `A2`.
- Do not re-run `pkill -f mnemos` — it matches the agent's own shell. Kill by port/PID.
