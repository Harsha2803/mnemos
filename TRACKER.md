# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It states what is built, the constraints
> you must not violate, and the exact next task. When you finish work, update this file
> **and [`docs/ADAPTATION.md`](docs/ADAPTATION.md)** *in the same commit* — a stale
> tracker is worse than none.

**Last updated:** 2026-08-10
**Phase:** **A — make it a chatbot.** `A0` ✅, `A1` ✅, `A2` ✅ — **you can sign in at
`http://localhost:3000`, upload a document, ask about it, and click the citation to see the
passage the answer came from.** What is still missing is the database (`A3`) and a router
that picks the flow for you (`A4`)
**Next task:** `A3` — **ask about your data in English**, fully specified in §5. Take them
one at a time, in order
**Branch:** `feat/a3-nl2sql` off `main`. **`main` contains M1+M2 (PR #1), M3.1–M3.3 (PR
#2), the slice plan (PR #3), CI (PR #4), M3.7 bootstrap (PR #5), F0 the app shell, M3.4's
backend half, the re-plan (PR #8), the compose fixes and smoke job (PRs #9, #10), `A0` the
auth surface (PR #11), `A1` the LLM gateway, chat persistence and streaming (PR #13), and
`A2` RAG over uploaded documents (PR #14)**

> ### 2026-08-08 — a marathon run, §0 rule 9 suspended for its duration
>
> The project owner asked for the whole remaining plan in one continuous run rather than
> one milestone per session. Rule 9 below is suspended **for this run only** — every other
> rule in §0 stands, most importantly rule 5 (no placeholders) and rule 8 (UI ships with its
> backend). Milestones still get their own branch, their own PR, their own commits and their
> own entry here; only the "stop after one and hand off" instruction is lifted. If you are
> reading this in a future session and rule 9 says "one task per session" again, that is
> correct — it reverts once this run ends, and this note stays as the record of the one time
> it did not apply.

> ### 2026-08-02 — the plan was re-cut around the product, and the milestones renumbered
>
> **What was wrong.** The old plan reached a chatbot at `M8`, RAG at `M9` and NL2SQL at
> `M10` — four milestones and several sessions of work in, with no conversation surface
> and nothing a person could be shown. Everything built was infrastructure: a 41-table
> schema, row-level security, an identity stack, a design system. All of it real, none of
> it demonstrable. A plan that reaches its own subject last is mis-ordered.
>
> **What was also wrong: the pitch.** §1 used to read *"an AI workspace chatbot whose
> context is a compiled artifact"*, and the README led with benchmark numbers about
> superseded document revisions. That is a research claim using a chatbot as its harness.
> The actual goal is the reverse — **an assistant with the full feature surface of a
> production platform**, where compiled context is one strong capability among many and
> earns its place by being measured, not by being the headline.
>
> **What changed.** Milestones are re-cut into four phases (§3.0). Phase A drives straight
> at a working chatbot: sign in, talk to it, then documents, then the database, then the
> router that chooses between them. Phases B–D layer on the platform depth, the enterprise
> governance and the ship polish. The memory/context kernel is **not dropped and not
> demoted in quality** — it is split, so its retrieval half lands early where RAG needs it
> (`A2`) and its governance half lands as its own deep slice with the inspector and the
> benchmark (`C4`).
>
> **Nothing built is scrapped.** Every milestone already merged is foundation under the new
> plan; the old `M`-numbers are mapped onto the new IDs in §3.0 so no work is lost or
> rediscovered. See the new constraint **C14**, which is the rule that stops this drift
> happening again.

> **2026-08-02 — the project is built in vertical slices.** Every milestone ships its
> backend *and* the UI for that backend. The old plan deferred the entire frontend to a
> single milestone `M13`; that milestone is **dissolved** and its contents redistributed
> (§3.0). The reason is in §2 C12: a feature with no UI is a feature nobody has used, and
> a year of backend with no screens is a portfolio piece that cannot be demonstrated.

---

## 0. Agent operating instructions

1. **Read in this order:** this file → [`docs/ADAPTATION.md`](docs/ADAPTATION.md) →
   `README.md` → the module you are changing →
   [`docs/CodingStandards.md`](docs/CodingStandards.md) for backend work, or
   [`docs/DesignSystem.md`](docs/DesignSystem.md) for **any** frontend work.
   This file tells you *what to do next*. ADAPTATION tells you *what the thing is* —
   architecture, the capability inventory, the schema plan, and the milestone ledger.
   DesignSystem tells you *what it looks like* and is not optional reading before you
   write a component.
2. **Do not re-litigate decisions in §2 or in ADAPTATION §9.** They are settled and
   several are load-bearing for numbers published in the README. If you believe one is
   wrong, write an ADR superseding it — do not silently deviate.
3. **Every change ends with:** `pytest` green + `alembic check` clean + benchmark re-run
   *if the retrieval or compile path moved* + README numbers updated if they moved +
   **this file and ADAPTATION.md both updated** + a conventional commit.
4. **If you change anything in the retrieval or compile path, re-run the benchmark and
   paste the new numbers into the README.** The README publishes measured results; a
   change that moves them and does not update them makes the repository dishonest.
5. **No placeholders, no `TODO`, no stubbed returns.** Split a task rather than stub it.
6. **Commits are scoped.** One logical change per commit, never a bulk drop of unrelated
   files.
7. **Every branch gets a PR the moment it has a commit** — draft if the work is
   unfinished. A branch without a PR is a branch that gets lost.
8. **A backend task is not done until its UI slice is done.** See §2 C12 and §3.0. If
   you land an endpoint, the screen that calls it is part of the same milestone — either
   in the same commit or in the next one, never in a later milestone. If the UI genuinely
   cannot be built yet, say why in §4 rather than leaving it implied.
9. **One task per session.** Finish whatever the previous session left unfinished; if
   nothing is pending, implement exactly one task from §5 and stop. Do not continue to
   the next task and do not start it while asking whether to. The next task gets a new
   session — that is deliberate, to spend usage limits on fresh context rather than on a
   long one. If a task proves bigger than it looked, split it, land the first piece
   properly, and rewrite §5 so the remainder is fully specified for the next agent.
   **Suspended once, deliberately, starting 2026-08-08:** the project owner asked for the
   remaining plan (`A1` through `D1`) in one continuous run rather than one milestone per
   session, to see the whole thing through. Every other rule in this section still applied
   during that run — each milestone still got its own branch, its own PR, its own commits
   and its own entry in §3, and §5 was still rewritten before each one was built. Only the
   "land one and stop" instruction was lifted, and only for that run. Unless a future
   instruction says otherwise again, this rule is back in force for whoever reads it next.

---

## 0.1 WHAT THIS PROJECT IS FOR — read this before anything else

Mnemos is a **portfolio-grade implementation of the capabilities its author has production
experience building**: retrieval over documents, natural language over a warehouse, tool
calling, ingestion pipelines, multi-tenant identity, and the operational scaffolding a real
platform needs. It exists to be *shown* — run it, sign in, ask it something, watch it
answer from a document and from a database.

**It is an independent implementation, not a port of anything.** Every file is written
fresh. See **C11**: the author's employer's codebase is not a reference, not a source, and
not to be read. The capability *list* below is what a platform of this kind needs — which
is public knowledge about the shape of the problem, not anybody's intellectual property.

**The feature surface, in full.** All of it is in the plan; none of it is aspirational
decoration:

| Area | What ships |
|---|---|
| **Conversation** | Sessions, messages, token-by-token streaming, folders, bookmarks, feedback |
| **RAG** | Upload → extract → chunk → embed → hybrid retrieval → answer with click-through citations |
| **NL2SQL** | Schema introspection, business glossary, generated SQL, AST read-only guard, read-only DB role, result grid, narration |
| **Tools** | MCP registry, per-user credentials, approval gates, trust tiers, and a bounded agent state machine over them |
| **Routing** | Classify a message to chat / RAG / NL2SQL / tools, and show *why* it was routed there |
| **Ingestion** | Object storage, source connectors, an event bus, jobs with heartbeat, retry and stuck-job detection |
| **Identity** | OIDC + internal auth, platform JWT with refresh rotation, API keys, RBAC, tag-scoped ACLs, per-tenant row-level security |
| **Governed context** | Bitemporal memory with supersession, a budgeted context compiler, and an inspector that shows what was admitted, what was excluded and why |
| **Operations** | Versioned prompt store, cost and token ledger, audit log, realtime WebSocket, migrations, CI, end-to-end tests |

The milestone plan is §3.0 here; the architecture, schema and design rationale are in
**[`docs/ADAPTATION.md`](docs/ADAPTATION.md)**. Read that next.

The v0.1 kernel is preserved in `backend/src/mnemos/_v1/`. It is **ported, not rewritten**,
in two halves: retrieval onto pgvector in `A2`, memory governance and the context compiler
in `C4`.

## 1. What this is (30 seconds)

**Mnemos — an enterprise AI assistant.**

One conversation surface. Ask it something and a router decides whether the answer needs
your documents (**RAG**), your database (**NL2SQL**), a tool (**MCP**), memory, or a
combination — then answers with citations you can click into. Underneath it is
multi-tenant, authenticated, authorised and audited, because that is what separates an
assistant from a demo.

**The one deep technical claim**, and it is measured rather than asserted: every prompt is
a **compiled, budgeted artifact you can open**. In the v0.1 kernel (neural embedder,
800-token budget, 23 questions), a naive prompt quoted a **superseded policy revision in
100% of prompts**; compiled, **0%**. Superseded memory facts: 61% → 0%. Restricted-content
leak: 13% → 0%. Duplicate token waste: 6.9% → 1.1%. Answer retention: 100% both. Latency:
69 ms → 81 ms.

**These numbers were measured on SQLite** and must be re-run when the kernel finishes its
port in `C4`. Until then the README must say so.

---

## 2. Non-negotiable constraints

| # | Constraint | Why |
|---|---|---|
| C1 | **Zero paid dependencies in the default path.** No API key for any capability. | The benchmark must reproduce on any machine |
| C2 | **Default embedder needs no download.** Neural is opt-in via the same port. | Same |
| C3 | **`tokens_consumed <= budget` is an invariant, not an estimate.** | Published claim; guarded by `test_compiled_prompt_never_exceeds_budget`, a 300-case randomised test, **and a CHECK constraint on `context_bundle`** |
| C4 | **Authorization is evaluated inside the scan. Post-filtering is banned.** | Published claim; `test_acl_pushdown_beats_post_filtering_on_yield` |
| C5 | **Memory is never overwritten.** Writes supersede and close belief time. | Published claim; the staleness metric depends on it. Now also enforced by `ex_memory_one_live_fact_per_scope` |
| C6 | **Superseded document revisions are excluded in the scan, not down-ranked.** | The headline number. Obsolete text often out-ranks current text |
| C7 | **Utility must be calibrated from rank before allocation.** | Raw RRF scores are nearly flat; skipping this makes the allocator buy boilerplate. Regression test pins the dynamic range |
| C8 | **Conflict losers are demoted and recorded, never silently dropped.** | |
| C9 | **Never use the work email/account** (`@jktech.com`, `harshaJKT`). Personal only. | Two GitHub accounts are authenticated in `gh`; confirm `Harsha2803` is active before any push |
| C10 | **The baseline must stay a fair representative**, not a strawman. `test_naive_arm_does_include_superseded_revisions` guards this. | A rigged baseline invalidates everything |
| C11 | **`jiva/` is not a reference. Do not read it, do not map from it, do not cite it.** Mnemos is an independent implementation of capabilities the author has production experience in — the capability *list* is public knowledge about the shape of the problem; any particular codebase's realisation of it is not. | See ADAPTATION §2. Employer IP in a personal repo is a real legal problem, and a project that documents itself as a mapping *from* an employer system invites exactly that reading even when every line is original |
| C12 | **Every feature ships its UI in the same milestone.** Backend and frontend advance together; no milestone is complete with an untouched `frontend/`. | A capability with no screen is one nobody has exercised end to end. It also hides integration defects — M3.2a was a leak invisible to every unit test because nothing looked at the wire |
| C13 | **The UI follows [`docs/DesignSystem.md`](docs/DesignSystem.md).** Tokens are the only source of colour, type, spacing and radius. | Consistency is the whole value of a design system; one component with a hard-coded hex is the crack it starts leaking through. The system draws its *ideas* from Apple's design resources — type scale, spatial rhythm, materials, motion character — but the palette, accent and identity are Mnemos's own; §0 there records which Apple assets are off-limits and why |
| C14 | **Every milestone ends with something a person can *do* in the running app.** Not an endpoint that exists, not a table that is filled — a sentence of the form "you can now ___" that a stranger could perform at `http://localhost:3000`. If a milestone cannot produce that sentence, it is infrastructure and must be folded into the milestone it serves rather than standing alone. | This is the rule the 2026-08-02 re-plan exists to install. The old plan reached its own subject — a chatbot — at `M8`, because each milestone was scoped by *layer* rather than by *capability*, and layers are invisible from outside. Infrastructure is not forbidden; standing alone in the plan is |

---

## 3. Current state — what is actually built

Milestone ledger and exit criteria live in [ADAPTATION §7](docs/ADAPTATION.md#7-milestones).
Detailed evidence for each ✅ is in [ADAPTATION §8](docs/ADAPTATION.md#8-current-state).

### 3.0 The plan — four phases, and the sentence each one earns

Every milestone ships its backend *and* its UI (C12), and every milestone ends with a
sentence of the form **"you can now ___"** performable at `http://localhost:3000` (C14).
That right-hand column is not a summary — it is the exit criterion.

**Phase A — make it a chatbot.** The product surface, in the order that makes it usable.

| ID | What it builds | You can now… | Status |
|---|---|---|---|
| **A0** | Sign-in screen + browser session handling (M3.4's UI half) + the fail-closed route guard (deny by default, from old `M3.6`) | **sign in through Keycloak, stay signed in across a reload, and sign out** — and no route added after this is reachable unauthenticated | ✅ |
| **A1** | LLM gateway (Ollama) · chat sessions + messages · SSE streaming · the chat surface | **talk to it** — ask a question and watch the answer stream in token by token | ✅ 2026-08-08 |
| **A2** | Upload → extract → chunk → embed (pgvector HNSW) · retrieval ported from `_v1` · RAG flow · citations · knowledge library | **upload a document and ask questions about it**, with citations you click into | ✅ 2026-08-10 |
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
| **C1** | API keys (old `M3.5`) · full RBAC permission matrix + tag-scoped document ACLs (old `M3.6`) · keys UI + real 403 states | **issue an API key, call the API with it, and watch a user without the permission be refused** — in the UI and at the wire | ⬜ |
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
| **M3.1–M3.3** | Identity domain types · the provider seam (internal + OIDC) · the split-horizon OIDC round trip | ✅ |
| **M3.4** (backend) | Platform JWT on HS256 · refresh rotation with family revocation · token endpoints | ✅ |
| **M3.7** | `mnemosctl bootstrap` — first org, admin, system roles, provider rows | ✅ |
| **F0** | The app shell: Next.js, design tokens, three-column layout, theming, primitives, generated API client | ✅ |
| **F0a** | CI — pytest, ruff, mypy `--strict`, `alembic check`, and the frontend gate on every PR | ✅ |

**Old milestone numbers, mapped.** Nothing was dropped; `M4`–`M14` were re-cut, not
discarded. If you find a reference to an old ID anywhere, this is the translation:

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
| `M13` frontend | dissolved into `F0` + a UI slice per milestone | Unchanged by this re-plan |
| `M14` realtime + e2e + docs | `D1` | |

### ✅ A2 — ask about your documents, verified 2026-08-10

**You can now upload a document, ask a question about it, and click the citation in the
answer to see the exact passage it came from.** That is the sentence C14 asks for, and it
is the one that makes the "grounded in your content" claim demonstrable rather than
architectural.

| Layer | What landed |
|---|---|
| `platform/objectstore/` | `ObjectStore` port + `S3ObjectStore` over MinIO. boto3 has no async client, so every call goes through `anyio.to_thread.run_sync` (CodingStandards §3) |
| `features/knowledge/domain/` | Ported from `_v1`: `chunk_text` (structure-aware, char offsets retained), `HashingEmbedder`, `HeuristicTokenizer`, RRF fusion, Jaccard dedup. All pure |
| `features/knowledge/adapters/extraction.py` | Text/Markdown/PDF, off the event loop. An unsupported media type is a named `ValidationError` |
| `features/knowledge/adapters/repository.py` | Documents, chunks, embeddings. Content-hash dedup checked *before* extraction, so a duplicate upload costs one `SELECT` |
| `features/knowledge/adapters/retrieval.py` | The vector operator over pgvector HNSW and the lexical one over pg_trgm, **both with the ACL predicate and `is_current` inside the scan** |
| `flows/rag/` | Prompt assembly from numbered passages, citation extraction, and the streaming flow reusing `A1`'s `ChatModel` port and streaming shape unchanged |
| `entrypoints/api/routers/knowledge.py` | `POST/GET/DELETE /v1/knowledge/documents` |
| `frontend/src/app/(app)/knowledge/` | The library: upload, list, delete with a naming confirmation |
| `frontend/src/lib/inspector/`, `components/shell/InspectorContent.tsx` | The inspector's first real content — the cited passage and its char span |

**The two constraints this milestone exists to honour, and how each is asserted.**

*C4 — authorization is evaluated inside the scan; post-filtering is banned.*
`test_acl_pushdown_beats_post_filtering_on_yield` is CodingStandards §9's mandatory case 3.
Ten documents on one topic, eight tagged to a role the caller does not hold, `k=3`:

```
pushdown  (predicate in the WHERE)  -> 2 accessible chunks   <- both that exist
post-filter (top-k then drop)       -> 0 accessible chunks   <- k spent on denied rows
assert pushdown_yield > post_filter_yield
```

The post-filtering arm is written out in the test *only to measure it*, the same way the
README's benchmark keeps a fair naive arm (C10). Without it the inequality would be an
assertion about one number.

*C6 — superseded revisions are excluded in the scan, not down-ranked.*
`test_a_superseded_document_revision_is_excluded_from_the_scan_not_down_ranked` uploads two
handbook revisions, retrieves, supersedes, retrieves again, and asserts the old text is
**absent** rather than lower:

```
before mark_superseded : "capped at ten working days"  present
after  mark_superseded : "capped at ten working days"  absent
                         "capped at five working days" present
```

Asserted by absence deliberately: obsolete text is often the *better* lexical match, which
is exactly why ranking cannot fix it and why this is the README's headline number.

**Evidence in a real browser against the rebuilt compose stack** (signed in as
`analyst@mnemos.local`, §4 item 40):

```
Knowledge -> upload handbook.txt  ->  "1 passages · 220 B · ready"
Chat -> New chat -> [x] Use documents
  "How many days of unused leave can I carry over?"
  -> "[1] Employee Handbook 2026 states that carry-over of unused discretionary
      leave into the following calendar year is capped at five working days."
click [1] -> inspector:
  Source [1] · Document passage · Characters 0–310 · relevance 0.29
  "Employee Handbook 2026 / Leave and time off / Carry-over of unused
   discretionary leave into the following calendar year is capped at five
   working days. ..."
```

And through the API against the same stack, `flow` and the citation row are real columns
rather than a rendering:

```
POST /v1/chat/sessions/{id}/messages  {"use_documents": true}
  done frame: {"flow":"rag","model":"qwen2.5:3b-instruct","prompt_tokens":181,...}
GET  /v1/chat/sessions/{id}
  [assistant] flow=rag
  citation [1] chunk=019fe21b... span=0-377
```

| Check | Result |
|---|---|
| `make test` | **278 passed** (was 250; +17 knowledge domain, +11 knowledge endpoints) |
| `make lint` | clean |
| `make types` | `mypy --strict`, clean on 153 source files — **scope widened** to `flows/` and `platform/`, since `A2` is the first milestone with real logic in `flows/` (Makefile and CI both) |
| `make check` | "No new upgrade operations detected" — **no migration**; `M2` created every table this writes to |
| `npm run test` | **89 passed** (was 82; +1 composer toggle, +4 knowledge library, +2 citations) |
| `npm run lint` · `npx tsc --noEmit` · `npm run build` | clean |
| `npm run test:e2e` | **9 passed**, and run twice consecutively to prove it leaves no residue — the knowledge spec deletes its own document and `SELECT count(*) FROM document` returns 0 afterward |
| `/readyz` | `{"postgres":"ok","redis":"ok","ollama":"ok","objectstore":"ok"}` |
| `gh auth status` | `Harsha2803` active (C9) |

**A layout bug the e2e suite found and unit tests structurally could not.** The sidebar's
destinations list is a flex child, and a flex child shrinks below its content by default —
so on a stack with enough accumulated conversations the list was squeezed until the
"Conversations" header overlapped it and intercepted clicks meant for the nav. It only
reproduces with a long session list, which is to say only on a stack somebody has actually
used, which is why it survived every green single-spec run. `shrink-0` on the
destinations, scroll on the conversations alone. Same lesson as §4 item 32 in a new place:
the state you develop against is not the state a user arrives in.

**Deviations from the written spec, both deliberate:**

- **`flows/rag/` duplicates `ChatService.stream_reply`'s loop rather than sharing it.**
  The layering rule (ADAPTATION §5) is that `features` must never import `flows`; having
  `ChatService` call the RAG flow would invert it, and having the flow subclass the service
  would couple two things whose only shared part is a `while` loop over model events. The
  duplication is a page of straightforward code and is the cost of the rule, noted here so
  a later reader does not "fix" it by breaking the layering.
- **`features/llm/` still has no `application/`, and `features/knowledge/` gained one.**
  Consistent with `A1`'s recorded deviation: a package gets an `application/` when it has a
  use case, and `KnowledgeService` is one.

**Explicitly deferred, and where to:** the six-phase context compiler, the budget allocator
with section floors, trust fencing and the provenance manifest are `C4` — `A2` truncates in
fused-score order and says so in `domain/retrieval.py`'s docstring. Ingestion runs
synchronously in the request handler; `ingest_job`/`ingest_job_event` exist and are unused
until `B2`. `_v1`'s `calibrate_utility` and `resolve_conflicts` are not ported, for the
reasons in that same docstring.

### ✅ A1 — talk to it, verified 2026-08-08

**You can now sign in, ask Mnemos a question, and watch the answer stream in token by
token, in a conversation that survives a reload.** It answers from the model alone — no
document, no database, no tool — which is a complete milestone rather than half of `A2`,
because the gateway and the streaming endpoint both of those land behind are built once,
properly, here.

| Layer | What landed |
|---|---|
| `features/llm/domain/model.py` | `ChatModel` — a `Protocol` with `stream`, `complete`, `health`, narrow on purpose so `A4`'s router and `C2`'s cost ledger can swap models without touching a call site |
| `features/llm/adapters/ollama.py` | `OllamaChatModel` over `/api/chat`. Every failure becomes `UpstreamError` (502) or `DependencyUnavailableError` (503, from `health()`); nothing above this layer ever sees Ollama's own wire shape |
| `features/chat/domain/` | `ChatSessionSummary`, `ChatMessageRecord`, `ChatSessionDetail`, `ChatSessionPage`, and the three streaming events `AssistantToken`/`AssistantDone`/`AssistantError` — all pure, no I/O |
| `features/chat/application/service.py` | `ChatService` — session CRUD plus `stream_reply`, the async generator the router primes and drains |
| `features/chat/adapters/repository.py` | `SqlChatRepository`. Message insertion computes its own ordinal in one `INSERT ... SELECT MAX(ordinal)` statement rather than a separate read-then-write |
| `entrypoints/api/routers/chat.py` | `POST/GET/PATCH/DELETE /v1/chat/sessions[/…]`, and `POST /v1/chat/sessions/{id}/messages` answering `text/event-stream` |
| `entrypoints/api/main.py` | Wires the gateway and the service into the lifespan; `/readyz` now calls `ChatModel.health()`; imports `mnemos.platform.models` for its side effect (see the trap below) |
| `frontend/src/lib/chat/stream.ts` | The SSE reader — `fetch` with a `ReadableStream`, not `EventSource` (deliverable 4's sharp edge) |
| `frontend/src/components/chat/` | `Composer`, `MessageBubble`, `MessageList`, `ChatSessionList` |
| `frontend/src/app/(app)/chat/` | `/chat` (empty state, "New chat") and `/chat/[sessionId]` (the conversation) |

**The persistence rule that makes an abandoned stream leave no trace.** The user's message
is written before the model is called (deliverable 2: a crashed generation leaves a
question, not nothing); the assistant's message is written **only after** the stream
completes, as the last statement in the loop rather than something a `finally` tries to
run on the way out. If the caller stops iterating — a real disconnect, or the test in
`test_an_abandoned_stream_leaves_no_half_written_assistant_message` closing the generator
early — execution never reaches that statement, so nothing half-written is ever committed.

**The router primes the generator once before opening the response.** `stream_reply` does
everything up to (and often past) the first token on its first `__anext__()` — session
lookup, persisting the question, opening the model connection — so a failure there (missing
session, Ollama unreachable) is still an ordinary exception the global handler renders as
404 or 502. Once a token has actually been yielded, the response has committed to 200 and
any later failure becomes an `error` SSE frame instead — asserted on the wire by
`test_an_ollama_failure_mid_stream_becomes_an_error_frame_not_a_crash`, which also asserts
the frame carries a constant public message and none of the underlying exception's detail.

**Evidence, in a real browser against the rebuilt compose stack** (headless Chromium,
`http://localhost:3000`, signed in as the seeded `analyst@mnemos.local` — see the item 40
trap below for why not `admin@mnemos.local`):

```
signed in -> landed on http://localhost:3000/
Chat -> New chat -> http://localhost:3000/chat/019fe1f6-...
composer: "In one short sentence, what is 2+2?"  ->  Enter

main, after the stream finished:
  You
  In one short sentence, what is 2+2?
  Mnemos
  2 + 2 equals 4.
  Send

page.reload() -> same URL, same two messages, still there
```

`frontend/e2e/chat.spec.ts` drives the same path headlessly and additionally asserts the
assistant bubble exists (with a "Thinking…" placeholder) **before** any token has arrived —
the frontend half of "never a spinner over a blank region" — and that the composer's
Send/Stop control tracks the stream. It skips loudly, naming exactly what is missing
(`web`/`api`/`keycloak`/`postgres`/`redis`/`ollama model not pulled`), the same shape as
`auth.spec.ts`.

| Check | Result |
|---|---|
| `make test` | **250 passed** (was 230; +10 `test_llm_gateway.py`, +10 `test_chat_endpoints.py`) |
| `make lint` | clean, `ruff check` + `ruff format --check` |
| `make types` | `mypy --strict`, clean on 115 source files |
| `make check` | "No new upgrade operations detected" — **no migration**; `chat_session`/`chat_message` already had every column from `M2` |
| `npm run test` | **82 passed** (was 76; +4 `Composer.test.tsx`, +2 the session page's streaming/axe tests) |
| `npm run lint` · `npx tsc --noEmit` · `npm run build` | clean |
| `npm audit` | 0 vulnerabilities in shipped dependencies (one pre-existing high finding in `@redocly/openapi-core`, a dev-only codegen tool not in the runtime image) |
| `frontend/e2e/auth.spec.ts` | **7 passed** (was 7 — see item 40; all seven now pass against this persistent stack, which they did not before) |
| `frontend/e2e/chat.spec.ts` | **1 passed**, 3 consecutive runs, no flakes |
| `gh auth status` | `Harsha2803` active, `harshaJKT` inactive (C9) |
| Clean-container rebuild | `docker compose up -d --build api web` from this branch's merged tree; `/readyz` reports `{"postgres":"ok","redis":"ok","ollama":"ok"}` |

**One CI contract change, made deliberately rather than left to fail.** `/readyz` now
depends on Ollama having the configured model pulled (deliverable 1's "fail at startup, not
at somebody's first message"). The `compose` job used to exclude `ollama` on the grounds
that nothing checked a model was loaded — true before this milestone, false after. It now
starts `ollama`, pulls `qwen2.5:3b-instruct` in its own step (so a slow pull reads as a slow
pull and not a wedged API), and only then waits for `/readyz`.

**Two things worth keeping deliberately:**

- **`test_a_message_streams_token_by_token_and_the_answer_is_persisted` asserts the SSE
  frames on the wire**, over a `FakeChatModel`, not the generator in isolation — the M3.2a
  lesson (a control tested one layer below where it takes effect is not tested) applied to
  streaming.
- **`test_the_upstream_error_never_carries_the_response_body_in_its_message`** restores the
  old M3.2a leak pattern in miniature: it proves `OllamaChatModel` puts Ollama's response
  text in `details` (log-only) rather than in `message` (public), which is what keeps a
  future `expose_details = True` on some other error type from turning an Ollama stack
  trace into an API response.

**Deviation, argued here rather than left implicit:** `features/llm/` ships `domain/` and
`adapters/` only, no `application/`. The task description asked for all three; there was no
use case to put there once the port and its one adapter existed — `ChatService` is where
the orchestration actually lives, in `features/chat/`, because assembling turns from
persisted history and a system prompt is a fact about chat, not about the model. An empty
`application/` package would have been the placeholder rule 5 forbids.

**Trap found and fixed, worth recording so it is not rediscovered:** nothing in the API
process had ever imported `mnemos.platform.models` (the file that exists specifically to
register every feature's tables on `Base.metadata` before Alembic compares against it —
see its own docstring). Every route built before this one happened to touch only tables
whose foreign keys resolve within their own feature, so the gap was invisible. The first
ORM operation on `chat_message` — whose `bundle_id` column has a `ForeignKey` to
`context_bundle`, a table `features/context/` owns — raised
`NoReferencedTableError` the moment a real query ran, in-process, entirely independent of
`alembic check` (which passes because Alembic imports the registry correctly and was never
the thing missing). Fixed with one import in `main.py`'s composition root; see §4 item 41.

### ✅ A0 — the auth surface, verified 2026-08-03

**You can now sign in through Keycloak at `http://localhost:3000`, stay signed in across a
reload, and sign out — and no route added after this is reachable unauthenticated.** That
is the sentence C14 asks for, and it is the first one this project has been able to write.
Before it, `M3.4` issued tokens nothing presented and `F0` was a shell with no way in.

| File | What it is |
|---|---|
| `entrypoints/api/security.py` | The guard. `enforce_authentication` is installed as an **application-level dependency**, which FastAPI merges into every route it registers — routers included later, routes added after startup, all of them. A route that decorates itself with nothing is authenticated. `public_route_paths()` is an **exact set of literal strings**; every near-miss (`/healthz/`, `//healthz`, `/api/v1/auth/token/steal`) is simply not in it and is denied |
| `features/identity/application/principals.py` | `PrincipalResolver` — token in, `Principal` out. Roles and tags come from the repository **on every request**; the token is asked exactly two questions, *is this signature ours* and *whom does it name*. Also the session-liveness check, which is what makes sign-out real |
| `features/identity/adapters/principals.py` | `SqlPrincipalRepository`. Four statements in **one** transaction under `app.current_org`, because roles read before a revocation and tags read after it produce a principal that never existed — and that principal is the input to an authorization decision |
| `entrypoints/api/routers/auth.py` | `GET /auth/me`, the first route in the system that is not in the allow-list. `authorize` and `callback` now answer a browser with redirects |
| `frontend/src/lib/auth/session.ts` | The access token, in a module variable and nowhere else |
| `frontend/src/lib/auth/refresh.ts` | The single-flight refresh: one shared promise within a tab, `navigator.locks` across tabs |
| `frontend/src/lib/api/client.ts` | `authenticatedFetch` — bearer attached, **one** retry after a refresh, `/auth/token` excluded from the retry by name |
| `frontend/src/components/auth/` | `SignInForm` (one constant error message), `SignInComplete`, `AuthBoundary` |
| `frontend/src/components/shell/AccountFooter.tsx` | The sidebar footer F0 reserved, now carrying a real email and org from `GET /auth/me` |
| `frontend/e2e/auth.spec.ts` + `playwright.config.ts` | Seven cases in a real browser against the real Keycloak |

**The acceptance test was written first and watched to fail.** `_probe/unguarded` is a
route registered exactly the way a feature router's endpoint is, with no dependency, no
decorator and no mention of authentication. With the application-level dependency removed:

```
$ pytest tests/test_route_guard.py           # dependencies=[...] deleted from create_app
FAILED test_unauthenticated_request_is_denied_by_default
    assert 200 == 401
19 of 24 failed
$ pytest tests/test_route_guard.py           # restored
24 passed
```

**Hydration proved against a real Postgres, with one token minted once and reused
verbatim.** If any of the three answers came out of the credential, all three would be
identical:

```
no role_binding                    ->  GET /auth/me  permissions []
INSERT role_binding (analyst)      ->  GET /auth/me  permissions ['knowledge:read','memory:read']
DELETE role_binding                ->  GET /auth/me  permissions []
```

The third line is not decoration. An additive implementation — a cache that unions
whatever it has seen — passes the first two and is exactly the thing that keeps a demoted
user's authority alive.

**Evidence in a real browser, against the live Keycloak** (headless Chromium; the API run
locally on `:8010` and the frontend on `:3100`, because the shared containers still carry
the pre-`A0` image and rebuilding them would have disrupted work in flight):

```
7 passed (4.8s)
  test_a_seeded_admin_signs_in_through_keycloak_and_lands_on_the_shell
  test_no_credential_ever_appears_in_a_url_or_in_web_storage
  test_a_reload_keeps_the_user_signed_in
  test_signing_out_returns_to_signin_and_a_protected_route_bounces_back
  test_an_unknown_workspace_returns_to_signin_with_the_same_message
  test_an_unauthenticated_visit_to_a_protected_route_redirects_to_signin
  test_the_api_refuses_a_protected_route_without_a_token

with the API stopped:                 7 skipped
  "the stack is not up: api unreachable"
```

**That closes `M3.4`'s one "could not verify".** Its live evidence drove `authorize` and
everything after the callback with `httpx`; what it could not do was fill in Keycloak's own
login form, because Keycloak 26 binds that form to a browser session it establishes with
cookies on the auth page. A browser driver does it in one line.

The bundle was grepped the way `F0` greps for hex literals. The **only** writes to web
storage in the shipped JavaScript are the theme preference and the validated return path:

```
localStorage.setItem(m,e     sessionStorage.setItem(n,e     sessionStorage.setItem(r,t
keys present:  mnemos.theme   mnemos.auth.returnTo   mnemos.auth.refresh (a lock name)
```

| Check | Result |
|---|---|
| `pytest` | **230 passed** in 32s (was 191; +39 — 24 route guard, 10 principal repository, 5 net in the auth endpoints) |
| hermetic subset | 204 passed, no Docker |
| `ruff check` + `ruff format --check` | clean, 151 files |
| `mypy --strict` on `core`/`features`/`entrypoints` | **Success: no issues found in 106 source files** |
| `alembic check` | "No new upgrade operations detected" — **no migration**; `session`, `role_binding` and `user_tag` already had every column |
| `npm run test` | **76 passed**, 11 files (was 41) |
| `npm run lint` · `npx tsc --noEmit` · `npm run build` | clean |
| `npm audit` | 0 vulnerabilities |
| axe | 0 violations on the sign-in screen, the waiting boundary, and the signed-in shell |
| CI | all three jobs green, including `compose` — the images build and the stack starts with these changes |
| `gh auth status` | `Harsha2803` active, `harshaJKT` inactive (C9) |

**Two deviations from the written spec, both deliberate.** `authorize` and `callback`
answer a browser with redirects rather than a JSON 401, and `GET /auth/me` is pulled
forward from `C1`. Both are argued in §4 items 34 and 35.

Five things worth keeping deliberately, because a later reader might take them for padding:

- **`test_a_route_in_the_public_allowlist_is_reachable_without_a_token` is not optional.**
  A guard that refuses everything passes the acceptance test above it. Without this
  control, the file would be satisfied by an application that 401s its own liveness probe
  — a working guard and a service no orchestrator will keep running.
- **`test_the_public_allowlist_is_exact_paths_and_never_a_prefix`** asserts that
  `/api/v1/auth` and `/api/v1/auth/token/steal` are *absent*. It exists to stop somebody
  "simplifying" the set into a `startswith`, which is one careless route name away from
  publishing everything beneath it.
- **`test_every_route_the_guard_cannot_reach_is_named_in_the_allowlist`.** `/docs`,
  `/redoc`, `/openapi.json` and `/docs/oauth2-redirect` are plain Starlette routes carrying
  no dependencies, so the guard never runs for them however it is installed. They are
  public by construction rather than by decision — which is fine right up until a future
  FastAPI adds a fifth. Naming them turns "public because of how the framework works" into
  "public because we said so", and this fails the day the framework disagrees.
- **`test_the_guard_reads_authority_on_every_request_and_not_once_per_token`** counts
  repository reads. Caching the hydration per token would quietly restore the property the
  token was built to avoid, and nothing else in the suite would notice; if a cache is ever
  added it must be keyed on something a revocation invalidates, and this is where that
  conversation starts.
- **`test_the_refresh_endpoint_is_never_itself_retried_after_a_401`** covers the door the
  single-flight guard does not. If the generic retry applied to `/auth/token`, a 401 from a
  refresh would trigger a refresh whose result is replayed against a chain that has already
  rotated — which the API reads as theft and answers by killing the family.

**The frontend suite was made offline, and CI is what found the need.** 74 tests passed and
the job still failed on `connect ECONNREFUSED ::1:8000`: a component test stubs `fetch`,
unstubs it in `afterEach`, and the session bootstrap's async chain is still running. On a
development machine that stray request lands on whichever API container is up and nothing
looks wrong. `vitest.setup.ts` now installs `globalThis.fetch` **before any test runs**,
which is therefore also what `vi.unstubAllGlobals()` restores, and `src/test/offline.test.ts`
pins both halves. Same lesson as §4.7 and §3's M3.2a entry, in a fourth place: the machine
you develop on is not the machine that proves anything.

### 🟡 M3 prerequisite — RLS made real, verified 2026-07-27

M3's acceptance criterion is `test_cross_org_read_returns_zero_rows`. Writing it found
that **the tenant isolation reported by M2 did not exist in the running system**. Two
independent defects, both now fixed, both with a test pinning them:

| Defect | Why it was invisible | Fix |
|---|---|---|
| The application connected as `POSTGRES_USER`, which the Postgres image creates as a **superuser**. RLS never applies to a superuser or to a `BYPASSRLS` role, so all 40 policies were inert | `db doctor` reports `relforcerowsecurity` from the catalogue, which was true. The policies existed; they constrained nobody | `0005` — `mnemos_app`, LOGIN NOSUPERUSER NOBYPASSRLS, DML only. `migrate` keeps the owner DSN; api/worker/realtime use the new role |
| An unscoped query **raised `22P02`** instead of returning zero rows. A reverted `SET LOCAL` leaves a placeholder GUC defined as `''`, not undefined, and `''::uuid` raises | Only reproduces on a connection that has already served a scoped request — i.e. every pooled connection, and no fresh one | `0006` — `NULLIF(current_setting('app.current_org', true), '')` |

Neither was ever exploitable through a *correctly filtered* query; the explicit `org_id`
filter held throughout. What was missing is the second, independent layer the threat
model's defence-in-depth argument depends on.

Evidence, as `mnemos_app` against the live stack:

```
before 0005, GUC = org A, two orgs present :  SELECT count(*) FROM tag  ->  2
after  0005, GUC = org A                   :  SELECT count(*) FROM tag  ->  1
after  0005, cross-org INSERT              :  ERROR: new row violates row-level
                                              security policy for table "tag"
before 0006, same connection after COMMIT  :  ERROR: invalid input syntax for
                                              type uuid: ""
after  0006, same connection after COMMIT  :  0 rows
```

| Check | Result |
|---|---|
| `pytest` | **28 passed** (23 `_v1` kernel + 5 tenant isolation) |
| `alembic check` | no drift |
| `alembic downgrade 0004` → `upgrade head` | clean both ways |
| `pg_roles` | `mnemos` super+bypass · `mnemos_app` neither · `mnemos_admin` bypass, NOLOGIN · `mnemos_app` ∈ `mnemos_admin` |

New in `platform/db.py`: `Database.elevated_session()` — `SET LOCAL ROLE mnemos_admin`
for the bootstrap transaction that has no org to scope to yet. It is a `SET ROLE` rather
than a standing privilege because **role attributes are not inherited through
membership**, so escaping isolation takes a deliberate statement that shows up in
`pg_stat_activity` and in the call site.

### ✅ M3.1 — identity domain types, verified 2026-08-02

`features/identity/domain/` now holds the pure types the rest of identity is written
in. **No SQLAlchemy anywhere in the layer** (the layering rule), proven by a subprocess
test rather than an in-process `sys.modules` check, which would pass vacuously because
the pytest process has already imported SQLAlchemy elsewhere.

| File | What it is |
|---|---|
| `ids.py` | `OrgId`/`UserId`/`RoleId`/`TagId`/`SessionId`/`ApiKeyId`/`ProviderId` — `NewType` over `UUID` so a transposed `revoke(user_id, org_id)` is a mypy error, not a leak |
| `permission.py` | `Permission` (`resource:action`) + `PermissionSet`. Grants may carry wildcards (`*:*`, `memory:*`); requirements may not — `allows()` raises on a wildcard requirement and `Permission.require()` refuses to build one. Parsing is tolerant (a garbage grant is dropped, not fatal); construction is strict |
| `tags.py` | `TagSet.overlaps()` — set intersection, symmetric, empty grants nothing. Kept a set-overlap *because that is what pushes into the SQL `WHERE`* (C4). Slugs lowercased to match `CITEXT` |
| `principal.py` | `Principal` — frozen (a mutable principal is a privilege-escalation primitive). Carries org, id, kind (`user`/`service`), permissions, tags, and exactly one of `session_id`/`api_key_id`, agreeing with `kind` (enforced at construction) |

| Check | Result |
|---|---|
| `pytest` | **39 passed** (was 28; +11 in `tests/test_identity_domain.py`), 3.9s |
| `pytest -q tests/test_identity_domain.py` | 11 passed, hermetic — no Docker |
| `ruff check` | clean on the new files |
| `mypy` (strict) | clean, 5 source files |
| `alembic check` | no new operations — M3.1 touched no schema |

Acceptance criteria from the old §5 all discharged: `test_permission_denies_by_default`,
`test_wildcard_grant_allows_specific_permission`, `test_wildcard_in_a_requirement_is_rejected`,
`test_tag_overlap_is_symmetric_and_empty_set_grants_nothing`, and the import-time
SQLAlchemy proof.

### ✅ M3.2 — the provider seam, verified 2026-08-02

Nothing *produced* a `Principal` before this. `features/identity/providers/` is the layer
that turns a presented credential into a verified `AuthenticatedSubject` — org plus
identity, and deliberately **not** a platform token and **not** a hydrated `Principal`
(roles and tags are the application layer's repository read; JWTs are M3.4).

| File | What it is |
|---|---|
| `core/security.py` | `PasswordHasher` — argon2id at OWASP parameters (m=64 MiB, t=3, p=4), on a worker thread. `verify(None, …)` still runs a real verification against a dummy hash, so "no such user" costs what "wrong password" costs. Also `digest_token` (SHA-256, high-entropy secrets only, with the "why not argon2 too" answer in the docstring) and `tokens_equal` |
| `providers/base.py` | `AuthenticatedSubject` (frozen; must name a local user **or** an external subject) and **two** protocols — `CredentialAuthProvider` and `TokenAuthProvider`. `denied()` builds the one denial this layer raises: constant `message` to the caller, real `reason` in `details` for the log |
| `providers/ports.py` | `OrgDirectory` / `UserDirectory` + `OrgRecord` / `ProviderRecord` / `UserCredentialRecord`. `ProviderRecord.kind` stays a raw `str` on purpose — an unrecognised value must deny, not raise out of an enum constructor |
| `providers/internal.py` | `InternalProvider`. One branch covers unknown user, inactive user and absent hash, so the three cannot drift apart in wording or timing |
| `providers/oidc.py` | `OidcProvider` + `HttpJwksCache`. Five checks: signature, asymmetric-only algorithm allow-list, configured issuer, `aud`-or-`azp`, `exp` with zero leeway. `require=["exp","iss","sub"]` — PyJWT does not verify a claim it cannot find |
| `providers/factory.py` | Strategy selection + composition root. Unknown/inactive org, unknown or disabled provider, unrecognised `kind` (including `api_key`, which is M3.5 and not a login strategy), incomplete OIDC config, and an ambiguous default all deny identically |
| `adapters/directory.py` | The SQLAlchemy side. All the ORM in the auth path lives here |

**The authentication path needs no `BYPASSRLS`** — this settles the first of §5's two open
design questions, in favour of **carrying the tenant in the credential**. `org` is the one
table without a policy (it is what every policy compares *against*), so resolving an org
slug runs on an ordinary unscoped session; every read after it runs with `app.current_org`
bound to the org just resolved, so RLS is doing real work underneath the explicit filter.
`Database.elevated_session()` keeps its single bootstrap call site.

| Check | Result |
|---|---|
| `pytest` | **72 passed** in 6.5s (was 39; +33 in `tests/test_identity_providers.py`) |
| `ruff check` + `ruff format --check` | clean on all new files |
| `mypy --strict` | clean, 8 new source files |
| `alembic check` | "No new upgrade operations detected" — M3.2 touched no schema |
| `gh auth status` | `Harsha2803` active, `harshaJKT` inactive (C9) |

All acceptance criteria discharged, plus more than were asked for:
`test_internal_provider_verifies_correct_password_and_rejects_wrong`,
`..._rejects_user_with_no_password_hash`, `test_oidc_provider_rejects_token_with_wrong_issuer`,
`..._with_bad_signature`, `..._that_is_expired`,
`test_factory_returns_the_strategy_named_by_the_identity_provider_row`,
`test_factory_denies_an_unknown_or_disabled_provider`, and
`test_providers_import_no_sqlalchemy_and_no_fastapi` (subprocess, same shape as M3.1's).

Three tests worth keeping deliberately, because they pin things the acceptance list did not
ask for and a later reader might delete as redundant:

- `test_oidc_provider_accepts_a_genuine_token` is the **control**. A validator that rejects
  everything passes every "rejects a forged token" case; without an acceptance test the
  other six prove nothing.
- `test_oidc_provider_rejects_an_unsigned_token` covers `alg: none` **and** the RS256→HS256
  confusion attack, where the token is HMAC-signed with the public key. The forgery is
  hand-built with `base64`/`hmac` because PyJWT refuses to *mint* it — a defence on the
  signing side that is no help at all on the verifying side.
- `test_internal_provider_denials_are_indistinguishable` asserts only the message, not the
  clock (a wall-clock assertion is flaky on a shared runner). The timing defence is
  structural — the miss path calls `verify(None, …)` — so the test's docstring says what
  would silently break if that call were deleted.

The JWKS cache's stampede guard was **wrong on the first pass and a test caught it**:
collapsing concurrent callers by "was this fetched in the last second" also swallowed the
deliberate re-fetch that key rotation depends on. It now compares entry *identity* — "did
somebody else already do my work" — which is the question actually being asked.

### ✅ M3.3 — split-horizon OIDC round trip, verified 2026-08-02

M3.2 could validate a token; nothing obtained one. M3.3 is the round trip, and it is the
first deliverable proved against **the realm as shipped** rather than against tokens the
test suite minted for itself.

| File | What it is |
|---|---|
| `providers/oidc.py` | `HttpOidcMetadata` — cached `/.well-known/openid-configuration` per issuer, shared with the JWKS cache. **Every discovered endpoint is constrained to the issuer's own prefix**, not just `jwks_uri`: a redirected `authorization_endpoint` is a phishing page wearing our login, and a redirected `token_endpoint` is where the authorization code gets posted. `public_authorization_endpoint()` re-hosts the discovered path on `issuer_public` — that function *is* split horizon |
| `application/oidc_login.py` | `OidcLoginFlow.begin()` / `.complete()`. PKCE S256, `state` verified and single-use, the org read from stored state and never from the callback's query string |
| `adapters/login_state.py` | `RedisLoginStateStore`. `GETDEL`, so read-and-delete cannot interleave — a `GET` then `DEL` has a window in which two concurrent callbacks both succeed, which is the replay the state exists to prevent |
| `entrypoints/api/routers/auth.py` | `GET /api/v1/auth/oidc/authorize` and `/callback`. Thin: HTTP in, flow call, HTTP out |
| `entrypoints/api/main.py` | The identity composition root in the lifespan — one `httpx.AsyncClient`, one hasher, one discovery cache shared by JWKS and the flow |
| `deploy/keycloak/mnemos-realm.json` | The API callback added to `redirectUris`. **Exact URIs, not `:8000/*`** — the wildcard was not needed and a narrower allow-list is free |

**Evidence against the live stack** (`docker compose up -d --force-recreate keycloak`
re-imports the realm; `start-dev` has no volume):

```
real id_token from the seeded realm user:
  iss   = http://localhost:8080/realms/mnemos      <- the PUBLIC issuer
  aud   = mnemos-web      azp = mnemos-web
realm redirectUris after re-import include
  http://localhost:8000/api/v1/auth/oidc/callback
GET /api/v1/auth/oidc/authorize?org=nope
  client sees : {"code":"unauthenticated","message":"authentication failed"}
  log sees    : reason="no org with slug 'nope'"
```

**That first line is the hard evidence for §4 item 12.** A token minted through the
browser-facing host carries `iss = issuer_public`, while the API's `issuer_internal` is
`keycloak:8080`. Trusting only `issuer_internal`, as the old §5 said, would reject **every
token a browser can obtain**. The deviation is not a shortcut; the instruction was wrong.
`aud = mnemos-web` on an ID token also confirms the `aud`-or-`azp` check (§4 item 13).

| Check | Result |
|---|---|
| `pytest` | **97 passed** in 5.5s (was 77; +20) |
| hermetic subset | 92 passed in 2.6s, no Docker |
| live Keycloak tests | 2, and they **skip** when the stack is down — verified by stopping it (`14 passed, 2 skipped`) rather than assumed |
| `ruff check` + `format` | clean |
| `mypy --strict` | clean on everything new; the 2 remaining in `identity/` are pre-existing `dict`-without-type-args in M2's `models.py` |
| `alembic check` | no new operations — M3.3 touched no schema |

Not done here, deliberately: **no platform JWT and no `session` row.** The callback returns
the verified subject. M3.4 replaces that response with a token pair; the refresh-rotation
chain is a whole test surface of its own and splitting it keeps both landable.

### ✅ M3.4 (backend half) — platform JWT + refresh rotation, verified 2026-08-02

M3.3 could prove a login *happened*. This is what makes one **last**: a 15-minute
access token, a rotating refresh token in an `httpOnly` cookie, and a family kill on
reuse. **Its UI slice landed in `A0`** — see the `A0` entry above; §4 item 24 is
discharged.

**The algorithm conflict is settled: HS256.** `ThreatModel.md` §5 said EdDSA and
`core/config.py` said HS256; both stood because nothing had issued a token. The argument
is now in `ThreatModel.md` §5.1 rather than in a table cell: api/worker/realtime are one
trust domain reading one `MNEMOS_JWT_SECRET`, so there is no verifier that must be unable
to sign — which is the only property asymmetric signing buys. EdDSA would turn one
environment variable into key generation, distribution and a JWKS endpoint, with the
private half ending up in that same variable. §5.1 also records what *reverses* it: the
first verifier outside the signing trust domain (a separately-deployed MCP tool service in
M11, an external audit consumer). `PlatformTokenConfig` already carries the algorithm as a
validated field, so that change is the allow-list plus a key pair.

The security-critical half is identical either way and is the **allow-list**:
`ALLOWED_PLATFORM_ALGORITHMS` is a one-element tuple passed to the decoder, and the token's
own `alg` header is never consulted.

| File | What it is |
|---|---|
| `domain/token.py` | `AccessTokenClaims` (exactly `sub`/`org`/`sid`/`iat`/`exp`/`iss`/`jti`, refusing `FORBIDDEN_CLAIMS` on the way *out* and the way *in*), `RefreshCredential` (`<org_slug>.<secret>`, `repr=False`), `TokenPair`. Pure — and now proven to import no **PyJWT** either, because the temptation with a claims type is to give it an `encode()` |
| `providers/platform.py` | `PlatformTokenCodec` + `PlatformTokenConfig`. Deliberately beside `oidc.py`: that one verifies a token another system minted, this one verifies a token we minted and could have forged. Opposite key material, identical header discipline |
| `application/tokens.py` | `TokenService.issue_for_subject` / `refresh` / `revoke`, the `SessionStore`/`AppUserStore` ports, and the JIT-provisioning decision |
| `adapters/sessions.py` | `SqlSessionStore` (compare-and-set rotation, recursive-CTE family walk) + `SqlAppUserStore` |
| `entrypoints/api/routers/auth.py` | Callback returns the pair instead of `SubjectResponse`; `POST /auth/token`, `POST /auth/token:revoke`; the cookie |
| `core/config.py` | `jwt_issuer`, `jwt_min_secret_length`, the named `DEV_JWT_SECRET` refused in production, the refresh-cookie settings |
| `docs/ThreatModel.md` §5/§5.1, `docs/APIContract.md` §1/§2 | Reconciled with the code in the same commits |

**Why the whole family dies.** Presenting a refresh token whose row already names a
successor is *proof* of theft, not a suspicion: the legitimate holder and the thief cannot
both hold the current token, so one is replaying a copy and nothing in the request can say
which. Refusing only the stale token leaves the thief holding the live one. Losing the
compare-and-set counts as the same evidence — same proof, different door — which is why the
frontend interceptor must collapse concurrent 401s into **one** refresh (§5 item 8).

**Just-in-time provisioning: on, and argued rather than assumed.** Refusing it would mean
nobody but the bootstrap admin (M3.7) can ever sign in, which is a reason to share an
account rather than a security control. What makes it safe is that provisioning grants
**identity, never authority**: no `role_binding`, no `user_tag`, `password_hash` NULL (so
M3.2's `InternalProvider` cannot password-authenticate the row). Matching is on
`external_subject` and **never on email** — an IdP email is a mutable, often unverified
attribute of an account *there*, so linking on it lets whoever controls that address
inherit a local user. An email already held by a different subject is a denial; linking is
an administrative action with a human in it.

**Evidence against the live stack** (API run locally on `:8010` against the compose
Postgres/Redis/Keycloak, an `acme` org seeded by hand and removed afterwards — there is no
`mnemosctl bootstrap` yet, §4 item 21):

```
authorize -> browser sent to  http://localhost:8080/realms/mnemos/protocol/openid-connect/auth
authorize?org=nope         -> 401 {"code":"unauthenticated","message":"authentication failed"}
JIT-provisioned app_user    : password_hash=None  role_binding rows=0  last_login_at set
access token header         : {"alg":"HS256","typ":"JWT"}
access token claims         : ['exp','iat','iss','jti','org','sid','sub']   <- no roles
POST /token (cookie only)   -> 200, refresh_token in body? False
  Set-Cookie                : mnemos_refresh=<secret>; HttpOnly; Max-Age=1209600;
                              Path=/api/v1/auth; SameSite=lax
  session rows              : A rotated_to=B reason=None / B rotated_to=- reason=None
replay the retired token A  -> 401, and BOTH rows now reason=refresh_token_reuse_detected
the live token B afterwards -> 401                      <- the family died, as designed
4 different failures        -> 1 distinct response body
POST /token:revoke, unknown -> 204 b''
CORS preflight from :3000   -> 200 origin=http://localhost:3000 credentials=true
openapi paths               : /api/v1/auth/{oidc/authorize, oidc/callback, token, token:revoke}
TokenResponse properties    : ['access_token','expires_in','org_slug','token_type']
```

That last line is the point of `TokenResponse` having no `refresh_token` field: the
generated frontend client cannot be handed one to put in `localStorage`.

| Check | Result |
|---|---|
| `pytest` | **183 passed** in 13.5s (was 97; +86) |
| hermetic subset | 167 passed in 5.5s, no Docker |
| new tests | 19 codec/claims · 31 rotation policy · 11 store-vs-Postgres · 25 endpoints |
| `ruff check` + `ruff format --check` | clean on all new and touched files |
| `mypy --strict` on `core`/`features`/`entrypoints/api` | clean, 28 files — **and the 2 pre-existing `type-arg` errors in identity's `models.py` are fixed** (§4 item 19) |
| `alembic check` | "No new upgrade operations detected" — **no migration**; `session` already had every column |
| `gh auth status` | `Harsha2803` active, `harshaJKT` inactive (C9) |

Acceptance criteria, all discharged: `test_rotated_refresh_token_revokes_family`,
`test_access_token_carries_no_roles_or_permissions`,
`test_a_token_signed_with_another_algorithm_is_rejected` (including `alg: none`),
`test_expired_access_token_is_rejected` (zero leeway, asserted at the boundary second),
`test_refresh_token_for_one_org_is_useless_against_another`, plus the two controls
`test_a_genuine_access_token_is_accepted` and
`test_a_verified_subject_receives_a_working_pair`.

Four things worth keeping deliberately, because a later reader might delete them as
redundant:

- **The boundary test was verified to fail.** `test_the_token_endpoint_leaks_nothing_in_its_error_body`
  and `test_every_token_failure_is_byte_identical` assert on the *response bytes*, and were
  checked by flipping `MnemosError.expose_details` back to `True`: 8 failures, with
  `"no active org with slug 'nosuchorg'"` and `"no session holds the presented refresh
  token"` appearing on the wire as distinguishable answers — a free tenant-enumeration
  oracle. Restored: 0 failures. That is the M3.2a lesson applied where it takes effect
  rather than one layer below it.
- **`tests/test_session_store.py` exists because the fakes would otherwise prove
  themselves.** Two claims are properties of Postgres, not of our code: the recursive walk
  that reaches a whole chain from a *middle* member, and that two genuinely concurrent
  rotations of one token cannot both win. The second is asserted with `asyncio.gather` over
  two real transactions.
- **PyJWT's `exp`/`iat`/`nbf` verification is turned off and replaced**, against the
  injected `Clock`. PyJWT calls `datetime.now(UTC)` internally, which defeats the port
  CodingStandards §5 exists to provide — a lifetime that cannot be tested without sleeping
  is one nobody tests at the boundary second. Same move `oidc.py` makes with `verify_aud`.
  `require` stays on, because without it "expiry is checked below" would be true and
  useless: there would be no `exp` to check.
- **The forgeries are hand-built from `base64`/`hmac`**, including the malformed-claim ones
  — PyJWT refuses to *mint* a non-string `iss`, which is a courtesy on the signing side and
  no help at all on the verifying side.
### ✅ M3.7 — `mnemosctl bootstrap`, verified 2026-08-02

M3.2 and M3.3 built a provider seam and an OIDC round trip that **nothing could
reach**: `ProviderFactory` reads `identity_provider` to decide which strategy to
build, and the table was empty on every database in existence. `bootstrap` is the
command that makes a fresh database one a person can sign in to.

| File | What it is |
|---|---|
| `domain/roles.py` | `SystemRole` + `SYSTEM_ROLES` — `admin` (`*:*`), `analyst` (11 grants), `user` (5). In `domain/` because M3.6's guard must require against the same roles this seeds; a constant duplicated between writer and reader drifts. Resources are the feature packages of ADAPTATION §5 so every permission traces to the code that will enforce it; actions are exactly four (`read`/`write`/`invoke`/`manage`). Slugs are the realm's roles minus the `mnemos-` prefix — realm roles are global and need a namespace, a `role` row is already scoped by `org_id` |
| `application/bootstrap.py` | `Bootstrap.execute()`, `BootstrapRequest` (validated at construction, so a future admin API inherits the rules), and the `BootstrapStore`/`BootstrapWriter` ports. **Both transactions are opened here**, so how much runs elevated is visible in the use case rather than buried in an adapter |
| `adapters/bootstrap_store.py` | The SQLAlchemy side and the system's only `elevated_session()` call site |
| `entrypoints/cli.py` | `mnemosctl bootstrap`, in `db doctor`'s argparse shape. Password from `MNEMOS_BOOTSTRAP_ADMIN_PASSWORD` or a double `getpass` prompt — **never an argument**, because argv is world-readable through `/proc/<pid>/cmdline`, lands verbatim in shell history and shows in `ps` |

**The elevation is one statement wide.** `without_a_tenant()` inserts the org and
nothing else — it is the only statement in the system that provably cannot carry
`app.current_org`, because the value it would carry is the value it is generating.
`scoped_to(org_id)` runs the other nine with the GUC bound, so a bug that computed
the wrong `org_id` is rejected by the policy's `WITH CHECK` instead of committed
by a privileged session left open because it was convenient.

**Idempotency: create-if-absent, and nothing existing is ever updated.** Not the
org name, not the admin's password hash, not `org.settings.default_provider`, not
a role's grants. An upsert wired into a deploy script would reset the
administrator's credential on every release, and would silently revert a default
changed through the app. The report is read back from the rows rather than echoed
from the request — the first draft printed the *requested* org name on a re-run
that had not renamed anything, which is the command lying about a write it did not
make. The cost of this choice is §4 item 20.

**Evidence against the live stack.** The `mnemos` database was empty (`SELECT
count(*) FROM org` → 0), so this is a genuine first bootstrap and not a re-run:

```
$ mnemosctl bootstrap --org-slug mnemos --org-name Mnemos \
      --admin-email admin@mnemos.local --admin-name "Ada Admin" \
      --oidc-issuer-public   http://localhost:8080/realms/mnemos \
      --oidc-issuer-internal http://keycloak:8080/realms/mnemos

org              : mnemos  (Mnemos) — created
org id           : 019fc0a6-c844-7332-97cd-63a811916a39
admin            : admin@mnemos.local — created
admin role       : admin — bound

  role         grants       status
  admin        1 grants     created
  analyst      11 grants    created
  user         5 grants     created

  provider     kind         status
  internal     internal     created
  keycloak     oidc         created

default provider : keycloak — set
sign in with     : org 'mnemos', email 'admin@mnemos.local'

second run, different password and different --org-name:
  every line reads "already present"; org name still 'Mnemos'
```

**The claim "nothing in M3.2/M3.3 can be exercised by hand" is now discharged**,
on the running API at `:8000`, and the contrast is the evidence:

```
GET /api/v1/auth/oidc/authorize?org=nope
  401 {"code":"unauthenticated","message":"authentication failed"}

GET /api/v1/auth/oidc/authorize?org=mnemos
  307 -> http://localhost:8080/realms/mnemos/protocol/openid-connect/auth
         ?response_type=code&client_id=mnemos-web
         &redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fv1%2Fauth%2Foidc%2Fcallback
         &scope=openid+profile+email&state=...&code_challenge=...
         &code_challenge_method=S256

GET /api/v1/auth/oidc/authorize?org=mnemos&provider=internal
  401 — a password provider reached through the OIDC endpoint is a misrouted
        request, not a fallback to try
```

That redirect is **split horizon working off the seeded row**: the API discovered
the endpoint over `issuer_internal` (`keycloak:8080`, which only resolves inside
the compose network) and re-hosted it on `issuer_public` (`localhost:8080`, the
only one a browser can reach). One URL in both columns would have produced a
redirect no browser could follow.

| Check | Result |
|---|---|
| `pytest` | **105 passed** in 13.1s (was 97; +8 in `tests/test_bootstrap.py`) |
| `ruff check` + `ruff format --check` on the diff | clean — see §4 item 22 for why the *repo-wide* run is not |
| `mypy --strict src/mnemos/core src/mnemos/features src/mnemos/entrypoints` | clean on everything new; the 19 remaining are all pre-existing (§4 item 19) |
| `alembic check` | "No new upgrade operations detected" — **M3.7 needed no migration**, as expected: every column it writes was created by `0001` |
| `gh auth status` | `Harsha2803` active, `harshaJKT` inactive (C9) |

The two tests worth keeping deliberately:

- `test_bootstrap_admin_can_authenticate_through_the_internal_provider` is the end
  of the loop. It goes through `ProviderFactory` rather than constructing an
  `InternalProvider` by hand, so it proves the seeded rows are the **shape** M3.2
  expects rather than merely present — the failure a row-count assertion cannot
  see, and the same lesson §4.7 records about `db doctor`.
- `test_bootstrap_does_not_leave_an_elevated_session_open` opens with a **control**
  asserting `current_user = mnemos_admin` inside `elevated_session()`. Without it,
  the assertions after the bootstrap would also pass against an implementation
  that never elevated at all, and the test would pin nothing.

**UI slice: deliberately none, and this is the record C12 requires.** A CLI is its
own interface. `bootstrap` is the command that runs *before* anybody can sign in,
so an authenticated screen for it would be a screen nobody can reach, and an
unauthenticated one would be an org-creation endpoint open to the internet. The
same sentence is in `cli.py`'s module docstring, where the next reader will be.

### ✅ M3.2a — the API error boundary stopped leaking `details`, 2026-08-02

Found immediately after M3.2, while reading `entrypoints/api/main.py` to plan M3.3. The
single `MnemosError` handler rendered `**exc.details` into the response body. M3.2's
`denied()` puts a constant message in `message` and the **real reason** in `details`
precisely so the reason stays internal — so the handler was undoing, on the wire, the
control the whole provider layer is built around.

Proved rather than assumed, by restoring the old handler and re-running the new test:

```
old handler, GET /_probe/denial   -> {"code":"unauthenticated","message":"authentication
                                      failed","reason":"no such user"}
old handler, GET /_probe/upstream -> {..., "dsn":"postgresql://mnemos:hunter2@postgres:
                                      5432/mnemos", "sql":"SELECT * FROM app_user ..."}
new handler, both                 -> code + message only; details go to the log
```

`MnemosError.expose_details` is now a `ClassVar` defaulting to **False**, with
`public_details` as the only thing the handler renders. `ValidationError` is the sole
opt-in: naming the offending field is the useful answer and reveals nothing the caller did
not send. `tests/test_error_boundary.py` (5 tests, hermetic — `Database` and `Cache`
construct lazily, so the lifespan runs with no Postgres or Redis) pins all of it.

**The lesson is the same one §4.7 records about `db doctor`, in a new place.** Every
provider test passed both before and after, because they assert on the raised exception and
never on the wire. A control that is only tested one layer below where it takes effect is
not tested. Anything else M3 claims about what a caller can observe should be asserted at
the boundary, not at the raise site.

### ✅ M1 + M2, verified 2026-07-27

| Area | What exists |
|---|---|
| `core/` | config, errors, structlog logging, clock, UUIDv7 ids, shared enums |
| `platform/` | async engine + tenant-scoped session (`app.current_org` GUC), Redis cache with TTL-mandatory locks, `models.py` metadata registry |
| `features/*/adapters/models.py` | 41 tables across nine groups |
| `migrations/` | `0001` schema · `0002` bitemporal EXCLUDE + cycle trigger · `0003` monthly partitions · `0004` FORCE RLS · `0005` unprivileged app role · `0006` RLS policy tolerates a reverted GUC |
| `entrypoints/` | api (`/healthz` vs `/readyz` split), worker (stuck-job reaper), realtime (WS over Redis pub/sub), `mnemosctl db doctor` |
| Stack | postgres · redis · minio · keycloak · ollama (`qwen2.5:3b-instruct`) · migrate · api · worker · realtime |

### ✅ v0.1 kernel, quarantined in `_v1/` (23 tests passing)

`core` · `embed` · `store` · `retrieval` · `compiler` · `baseline` · `ingest` ·
`dataset` · `bench` · `app` · `cli`. Ported, not rewritten, in M4.

### ⬜ Designed in `docs/` but NOT built

Neo4j knowledge graph (dropped) · agent runtime · MCP tool service · NL2SQL flow ·
OIDC/SAML auth · Celery workers · Next.js dashboard.

`docs/` describes the full target architecture. The gap is stated in the README and is
not a defect.

### Environment

| Fact | Value |
|---|---|
| Repo | `/home/shreeharsha/Personal/Projects/Resume_001/mnemos` |
| Python | 3.12.3, venv at `.venv` |
| Install | `.venv/bin/pip install -e "./backend[dev]"` |
| Stack up | `docker compose up -d` — nine services including `web`; no profile flag since F0 |
| Schema report | `docker compose exec api mnemosctl db doctor` |
| Migrations | `cd backend && MNEMOS_DATABASE_URL=postgresql+asyncpg://mnemos:mnemos@localhost:15432/mnemos ../.venv/bin/alembic upgrade head \| downgrade base \| check`. The DSN is explicit because the default in `core/config.py` names `mnemos_app` on `:5432`, which from the host is the machine's own Postgres and not the compose one |
| Tests | `make test` (or `cd backend && ../.venv/bin/python -m pytest`) → **250 passed** (needs Docker + Keycloak; see §4.8) |
| Fast tests | `make test-fast` — **226 passed**, ~29s. Its ignore list predates `test_principal_repository.py`, which also uses testcontainers and is not on it, so this still needs Docker despite the name; the 2 live-Keycloak tests still skip cleanly when the stack is down. Fixing the ignore list is a Makefile one-liner for whoever next needs a genuinely hermetic fast loop — `pytest -q tests/test_invariants.py` remains the actually-hermetic one (§4 item 8) |
| First-run setup | `mnemosctl bootstrap --org-slug <slug> --org-name <name> --admin-email <addr>`, password from `MNEMOS_BOOTSTRAP_ADMIN_PASSWORD` or the prompt. Idempotent; re-running is safe |
| Bootstrapped locally | org `mnemos` / admin `admin@mnemos.local` / password `mnemos-dev-admin-password` — a **dev-stack credential**, in the same class as Keycloak's `admin`/`admin` and MinIO's `mnemos-dev-secret`, and never to be reused anywhere real |
| Signing in through the browser | org slug `mnemos`, then Keycloak wants a **realm** credential — `analyst@mnemos.local` / `analyst` or `user@mnemos.local` / `user`, **not** `admin@mnemos.local`, whose realm and internal-provider identities collide on email and are denied by design (§4 items 37 and **40**) |
| Type check | `../.venv/bin/mypy --strict src/mnemos/core src/mnemos/features src/mnemos/entrypoints` — clean on everything M3 has touched; what still fails project-wide is listed in §4 item 19 |
| DB roles | `migrate` connects as `mnemos` (owner). api/worker/realtime connect as `mnemos_app` |
| Host ports | postgres `15432`, redis `6380`, api `8000`, realtime `8001`, keycloak `8080`, minio `9000/9001`, ollama `11434` |
| UI | **The app shell at `http://localhost:3000`** (F0). Also Swagger `http://localhost:8000/docs` · Keycloak `:8080` (`admin`/`admin`) · MinIO `:9001` (`mnemos`/`mnemos-dev-secret`) |
| Frontend gate | `cd frontend && npm ci && npm run lint && npx tsc --noEmit && npm run test && npm run build` → **76 tests pass**, all four clean |
| Browser end-to-end | `cd frontend && npm run test:e2e` — Playwright over the live stack, **7 passed**. Needs `npx playwright install chromium` once. Skips loudly, naming the unreachable service, when the stack is down. Not in CI (§4 item 39) |
| Regenerate API types | `cd frontend && npm run generate:api` against a running api. `src/lib/api/schema.ts` is committed and never hand-edited |
| Git identity | `Cheella Sree Harsha <cheellasreeharsha2803@gmail.com>` (repo-local) |
| GitHub | `Harsha2803/mnemos`, private. **Two accounts in `gh`; keep `Harsha2803` active** |

---

## 4. Known gaps and honest weaknesses

Recorded so they are not rediscovered as surprises:

> **A note on milestone IDs in this section.** Items written before 2026-08-03 name the
> milestone that owned a piece of work under the *old* numbering. Forward-looking
> references have been translated to the new IDs; references to milestones that have
> already **shipped** (`M1`, `M2`, `M3.1`–`M3.4`, `M3.7`, `F0`, `F0a`) are left as they
> are, because those are history and renaming history makes the evidence unfindable. If
> you meet an ID you do not recognise, §3.0 carries the full old → new mapping.

1. **Answer retention is a tie under a good embedder** (100% vs 100%). The corpus is
   5.4k tokens — too small for budget pressure to bite. Growing the corpus 10× is the
   single highest-value change to the *benchmark*; deferred until the kernel finishes its
   port (retrieval in `A2`, memory and the compiler in `C4`) so
   it is measured once, on Postgres, rather than twice.
2. **Duplicate waste rises at large budgets** (14% at 3000) because more
   near-threshold content is admitted. Dedup is a threshold, not a guarantee.
3. ~~**Brute-force cosine over all chunks** on every query in `_v1`.~~ **Discharged by
   `A2`, 2026-08-10** *for the live path*. `features/knowledge/adapters/retrieval.py`
   orders by pgvector's `<=>` through the HNSW index `M2` created, with the authorization
   and currency predicates in the same `WHERE`. The `_v1` kernel still contains the
   brute-force scan and still runs the published benchmark on it; that copy dies when the
   memory half is ported in `C4` and the benchmark is re-pointed at Postgres.
4. **`all_chunks()` reloads the whole corpus per operator call** — three times per
   compile. Still true **in `_v1` only**; the ported retrieval path (`A2`) never loads a
   corpus into Python at all. Dies with the rest of `_v1` at `C4`.
5. **No LLM in the loop in the *benchmark*.** The v0.1 benchmark measures *what reaches the
   model*, not answer correctness, and that is still true — `A1` and `A2` put a real model
   in the *product* path, but `bench.py` is still the deterministic-metrics harness and
   must stay one. An LLM-in-the-loop arm is possible now; it must be added *alongside* the
   deterministic metrics, never in place of them, whenever `C4` re-runs the benchmark.
6. **The heuristic tokenizer approximates BPE.** Within a few percent on English prose;
   a `tiktoken` adapter would remove the approximation.
7. ~~**RLS is untested by an automated test.**~~ **Discharged 2026-07-27**, and it was
   worse than "untested" — see §3. `tests/test_tenant_isolation.py` now proves it against
   a real Postgres. The lesson worth keeping: `db doctor` reported the catalogue
   faithfully and the catalogue was not the thing that mattered. **A schema-level report
   is not evidence that a control is in force.** Anything else claimed on the strength of
   `db doctor` alone deserves the same suspicion.
8. **The test suite now needs Docker.** `test_tenant_isolation.py` starts a
   testcontainers Postgres, so `pytest` went from ~1s and hermetic to ~25s and
   Docker-dependent. Accepted deliberately: tenant isolation is a property of Postgres,
   and a fake would only prove the fake isolates. The 23 `_v1` tests remain hermetic, so
   `pytest -q tests/test_invariants.py` is still the fast loop.
9. **`ruff check` is not clean on `tests/test_invariants.py`** — one `RUF059`
   (unused unpacked variable, line ~202). Pre-existing, inherited from v0.1, untouched
   because it is not in the M3 diff. One-line fix whenever that file is next edited.
10. **`context_bundle` and `bundle_item` have no writer yet.** The tables and the budget
    CHECK exist; the compiler that fills them is `C4`.
11. ~~**The frontend is still an empty directory.**~~ **Discharged by `F0`, 2026-08-02**,
    and the screens it named have since arrived: the sign-in form (`A0`), the chat surface
    (`A1`), and the knowledge library plus the inspector's first content (`A2`). What the
    inspector still lacks is the *context bundle* — what was admitted, what was excluded
    and why, and the budget spend — which is `C4`; as of `A2` it shows the cited passage
    and its char span, and its empty state says which half is still missing.
12. **Deviation (M3.2), now confirmed correct by M3.3: the OIDC validator trusts *two*
    configured issuers, not `issuer_internal` alone.** The old §5 said to validate `iss`
    against `issuer_internal`. **A real token from the live realm carries
    `iss = http://localhost:8080/realms/mnemos` — the *public* issuer** (§3, M3.3
    evidence), so the instruction as written would reject every token a browser can
    obtain. Original reasoning:
    Keycloak runs `start-dev` with `KC_HOSTNAME_STRICT=false`, so it stamps `iss` with
    whichever host minted the token — a browser token says `localhost:8080` while the API
    fetches JWKS from `keycloak:8080`. Accepting only the internal URL would reject every
    token a browser can actually obtain. Both URLs are configuration *we* control, so the
    property that matters is intact: **the token's own `iss` never decides**. Pinning
    Keycloak's issuer with `KC_HOSTNAME` instead would collapse this to one URL and is the
    cleaner long-term fix; it is a compose change, and M3.3 owns the realm edits anyway.
13. **Deviation (M3.2): the audience check accepts the client id in `aud` *or* `azp`.**
    Keycloak puts the resource audience in `aud` (usually `account`) and the client the
    token was issued to in `azp`. Requiring `aud == client_id` rejects ordinary Keycloak
    access tokens; accepting any `aud` accepts tokens minted for other clients in the same
    realm. "The client id appears in either position" is the check that actually means
    *this token was issued to us*. PyJWT's own `aud` verification is switched off and
    replaced rather than left on and worked around.
14. ~~**`ThreatModel.md` §5 (EdDSA) still contradicts `core/config.py` (HS256).**~~
    **Settled by M3.4 in favour of HS256**, with the argument written into
    `ThreatModel.md` **§5.1** rather than left as a table cell. Summary: api/worker/realtime
    are one trust domain reading one secret, so there is no verifier that must be unable to
    sign — the only property asymmetric signing buys. EdDSA would turn one environment
    variable into key generation, distribution, rotation and a JWKS endpoint, with the
    private half ending up in that same variable; there is no KMS in this stack (C1). The
    part that actually stops forgeries is identical either way and is the **allow-list**,
    never the token's `alg`.
    **What reverses it, written down so it is not re-litigated from scratch:** the first
    verifier outside the signing trust domain — a separately-deployed MCP tool service
    (`B3`), an external audit consumer, or tokens crossing an organisational boundary. At
    that point verification would require handing out the ability to mint.
    `PlatformTokenConfig` keeps the algorithm as a validated field for exactly that day.
15. ~~**No end-to-end proof against the live Keycloak yet.**~~ **Discharged by M3.3** —
    `test_a_real_keycloak_token_is_accepted_by_the_validator` and
    `test_the_realm_allows_the_api_callback_as_a_redirect_uri` run against the live stack,
    and were confirmed to *skip* rather than silently pass when it is down. It did surface
    the `iss` assumption, exactly as predicted; see item 12.
16. **The live-Keycloak tests point both issuers at `localhost:8080`.** From the host,
    `keycloak:8080` is a compose-network name that does not resolve, so the *two-issuer*
    logic is covered hermetically and the live tests cover "a genuine Keycloak token
    validates". Running them from inside the `api` container would exercise both at once
    and is the obvious improvement whenever the test suite gains a container-side runner.
17. ~~**The OIDC callback returns a subject, not a token.**~~ **Discharged by M3.4** — the
    callback returns `TokenResponse` and sets the refresh cookie, and
    `POST /v1/auth/token` rotates it. A session now survives a reload. What is still
    missing is the *browser* half that uses it; see item 20.
18. ~~**There is no CI. `.github/workflows/` does not exist**~~ — **discharged by PR #4**,
    which added `.github/workflows/ci.yml`: the backend job runs pytest (with a real
    Postgres and a real Keycloak, so the live tests run rather than skip), ruff, `mypy
    --strict` and `alembic check`; the frontend job runs `npm ci`, lint, `tsc --noEmit`,
    test and build. The history below is kept because it explains what the workflow had to
    solve. Before it, `gh pr checks` reported
    nothing and "the PR is green" meant *someone ran the gate locally and said
    so in the merge commit*. That is how PR #2 was merged (2026-08-02): `pytest` 97 passed,
    `ruff` clean, `mypy --strict` clean on new code, `alembic check` clean, pasted into the
    merge message. It is honest but it is not a control — it depends on the person
    remembering, and it cannot fail a merge. **A GitHub Actions workflow running the same
    four commands is a small task and should be picked up as `F0a` or alongside `M3.4`.**
    Note the wrinkle that makes it non-trivial: `pytest` needs Docker (testcontainers) and
    the 2 live-Keycloak tests need a Keycloak service — so the workflow wants
    `services:` containers, or it must run the 92-test hermetic subset and accept that the
    Postgres and Keycloak tests only run locally.
19. **`mypy --strict` is not clean repo-wide.** Two `type-arg` errors in
    `features/identity/adapters/models.py` (M2, `dict` without parameters) and four files
    in the quarantined `_v1/`. Neither is in any recent diff. The `models.py` pair is a
    two-line fix whenever that file is next touched; `_v1/` is fixed by the port (`A2`, `C4`).
    **Updated 2026-08-02 (M3.7):** it is 19 errors, not 6, because `dict`-without-args
    appears in **seven** `adapters/models.py` files, not one — plus one `no-untyped-call`
    in `realtime/main.py` and one `no-any-return` in `routers/auth.py`. All pre-existing
    and none in the M3.7 diff. `type_annotation_map` already maps `dict[str, Any]`, so the
    fix is genuinely mechanical.
20. **`bootstrap` does not reconcile an existing org with a changed `SYSTEM_ROLES`.**
    The idempotency rule is create-if-absent and *never update* (§3, M3.7) — chosen
    because the command takes a password and an upsert in a deploy script would reset the
    administrator's credential on every release. The cost lands here: adding a grant to
    `admin`/`analyst`/`user` in `domain/roles.py` reaches only orgs bootstrapped *after*
    the change. Nothing depends on this yet because the permission matrix (`C1`) does not
    exist, but it
    must be solved before it does — either a data migration per grant change or a separate
    `mnemosctl roles sync` that reconciles `is_system` roles only. A "just re-run
    bootstrap" answer is the wrong one and would drag the password rewrite back with it.
21. **`Database.elevated_session()` is not load-bearing today, and the M3.7 code says so
    rather than implying otherwise.** `org` is the one table migration `0004` deliberately
    left without a policy, so the bootstrap's org `INSERT` would also succeed on an
    ordinary `mnemos_app` session; the elevation is not what makes it work. It is used
    anyway, for one statement, because that statement is the only one in the system that
    provably cannot carry `app.current_org` — naming that in code is worth more than
    saving a statement — and because bringing `org` under a policy later (a parent org, a
    reseller, a soft-delete) would otherwise break bootstrap at the worst possible moment.
    The reasoning is in `adapters/bootstrap_store.py`'s module docstring, so a later reader
    who notices the same thing finds the answer instead of deleting the call.
22. **"`ruff` is clean" depends on which `ruff` you installed.** `pyproject.toml` pins
    `ruff>=0.7` and `mypy>=1.13`; a fresh venv on 2026-08-02 resolved **ruff 0.16.1** and
    **mypy 2.3.0**. Under that ruff, `ruff format --check .` wants to reformat **14
    pre-existing files** (`_v1/` and `tests/`, none touched by M3.7) and `ruff check .`
    reports 11 findings, 10 of them pre-existing. M3.7's gate was therefore run **scoped to
    the changed files**, which is honest but is not the same claim earlier milestones made.
    Two consequences: the CI workflow of item 18 must pin exact tool versions or it will
    fail its first run on code nobody changed, and the repo-wide reformat is a one-commit
    chore somebody should land on its own so it never contaminates a feature diff.
23. **The Keycloak realm users are not local `app_user` rows.** `bootstrap` seeds exactly
    one user, the admin, and it is a *password* account on the `internal` provider. The
    three realm users (`admin@`, `analyst@`, `user@mnemos.local`) can complete the OIDC
    round trip — M3.3 proved that — but land as an `AuthenticatedSubject` carrying an
    external subject and no local user. Just-in-time provisioning is M3.4's decision
    (§5), which is why bootstrap does not guess at it. The practical effect until then:
    the seeded admin signs in with the **internal** provider by naming it, while the org
    default sends the browser to Keycloak.

24. ~~**C12 is not satisfied for `M3.4`: the backend landed without its UI slice.**~~
    **Discharged by `A0`, 2026-08-03.** The sign-in screen, session handling and the
    protected shell are in `frontend/`, and a person signs in through a browser rather than
    by hand or through the test suite. Kept because the *reason* it was ever open is worth
    remembering: `frontend/` was an empty directory, so `F0` had to exist before a sign-in
    screen could be built *in* anything. That is a sequencing argument and it does not
    generalise — it was written down precisely so "the backend landed and the UI is next"
    could not become a habit.

25. **The refresh window slides; there is no absolute session lifetime.** Every rotation
    sets `expires_at = now + refresh_token_ttl_s`, so an actively used session never
    reaches an end — fourteen days is an *idle* timeout, not a maximum. Capping it needs
    the chain root's `issued_at`, which means either a walk to the root on every refresh or
    a `family_id` column and a migration. Neither is worth doing until a policy asks for
    it. Pinned by `test_the_refresh_window_slides_on_every_rotation` so it stays a decision
    somebody made rather than one nobody noticed.

26. **A user who deliberately opens two tabs mid-refresh revokes their own session.**
    **Largely closed by `A0`** — the browser client serializes refreshes across tabs with
    the Web Locks API, so tab B waits and then refreshes against the cookie tab A already
    rotated. The residue, and what is still unverified, is §4 item 36. The backend
    behaviour below is unchanged and is still the right trade —
    the alternative is two live chains from one credential, which is the state the family
    kill exists to prevent. It does mean the frontend interceptor in §5 item 8 is a
    *correctness* requirement and not an optimisation, and that a future non-browser client
    has the same obligation. If it proves painful in practice the fix is a short grace
    window keyed on `(session_id, presented_hash)` — deliberately not built on speculation.

27. **M3.4's original §4 items 21 and 24 are resolved, not deleted.** Item 21 ("nothing
    seeds an org") is discharged by `M3.7`, which merged first and seeded org `mnemos`;
    the prerequisite it warned about is satisfied. Item 24 (repo-wide `ruff` reports 10
    findings, not the 1 that item 9 claims) is the same finding as item 22 above, reached
    independently by two agents on two branches — which is itself the evidence that it is
    real and that the repo-wide format chore is overdue. Item 9's "one finding" claim is
    wrong and both of those items supersede it.

28. **`/readyz` publishes an empty response schema, so its generated type is `unknown`.**
    It returns a bare `JSONResponse`, so FastAPI describes the body as `{}` and
    `openapi-typescript` correctly emits `unknown` — which is honest, and useless to a
    caller. `frontend/src/lib/api/readiness.ts` therefore narrows the payload at runtime.
    That is **not** a hand-written mirror of a Pydantic model (there is no model to
    mirror), and it throws on an unrecognised shape rather than coercing one, because a
    green light beside a body nobody understands is worse than an error. **The real fix is
    a response model on `/readyz`**, and it belongs to the next task that touches Python.
    It is a five-line change and `A0` is the natural moment.
29. **Deviation (F0): `--ease-spring` was pseudo-code in DesignSystem §2.5 and now has a
    real value.** It was written `linear(/* or a spring via Framer Motion */)`, which no
    browser can parse, so the token could not be defined at all — and F0's own test that
    every documented token exists in `globals.css` failed on exactly that. It is now a real
    `linear()` easing with a 1.017 overshoot, and §2.5 carries the same value. Framer
    Motion is **not yet a dependency**: F0's only motion is one CSS width transition, and
    an unused animation library in `package.json` is a bigger lie than a missing one. It
    arrives with the first component that needs interruptible physics.
30. **jsdom cannot evaluate two of the things F0 asserts, so those halves are asserted
    differently and it is worth knowing which.** jsdom has no `prefers-color-scheme` and
    no layout, and its CSS parser predates cascade layers (`src/test/harness.ts` flattens
    them, or the suite would see eleven rules out of several hundred). So: theme
    *resolution* is asserted through real computed custom properties; the media block's
    `:root:not([data-theme="light"])` scope — which is the entire mechanism — is asserted
    against the compiled stylesheet; and both were then **confirmed in headless Chrome over
    CDP**, along with the 260/320/736px column widths and the absence of a theme flash. A
    control asserted only one layer below where it takes effect is not asserted (§4.7,
    §3 M3.2a). Playwright, at `A0`, is where this stops being a bespoke
    script.
31. **The frontend has no `mypy`-equivalent gate on the generated client's *runtime*
    shape.** `schema.ts` guarantees the types the API *documents*; it guarantees nothing
    about the body the API actually sends, and for `/readyz` it documents nothing at all
    (item 20). `parseReadiness` closes that for one endpoint by hand. If a third or fourth
    endpoint needs the same treatment, that is the signal to add a runtime validator
    generated from the schema rather than to write a third narrowing function.

32. **The whole stack was never rebuilt from source between M3.4 and F0, and `main` could
    not start.** `M3.4` added a minimum-length check on `jwt_secret` (an HMAC-SHA256 key
    shorter than its own digest signals a value nobody chose deliberately) but
    `docker-compose.yml` still shipped the 19-byte `dev-only-change-me`. The first
    `docker compose up -d --build api` after F0 merged put the API into a crash loop with
    `ConfigurationError: jwt_secret is shorter than an HMAC-SHA256 key should be`, and
    `web` never started because it waits on `api` being healthy. Fixed in the same commit
    as this entry.

    **Every test passed throughout.** M3.4's agent verified its work against an API it ran
    locally on `:8010` with its own settings, and its 191 tests construct
    `PlatformTokenConfig` directly — so nothing in the suite ever read
    `docker-compose.yml`. This is the same lesson as `db doctor` (item 7) and the error
    boundary (§3, M3.2a), in a third place: **a control verified one layer away from where
    it takes effect is not verified.** The concrete gap is that CI builds no images and
    runs no `docker compose up`, so "the stack starts" is asserted by nobody. A compose
    smoke job — build, `up -d`, poll `/readyz` and `:3000`, tear down — is the check that
    would have caught this. **It now exists** — the `compose` job in
    `.github/workflows/ci.yml` builds the images, starts the stack, waits for `/readyz` and
    for `:3000`, and checks `mnemosctl` shipped in the image. `ollama` is the one service it
    excludes, because nothing it asserts needs a 2 GB model pull.

33. **`core/config.py`'s default `database_url` points at `localhost:5432`, which on the
    development machine is a *different Postgres*.** The compose stack maps its Postgres to
    host port **15432** precisely because this machine already runs its own on 5432. So
    `cd backend && alembic check` from the host connects to the wrong server and fails with
    `InvalidPasswordError: password authentication failed for user "mnemos_app"` — and the
    worse outcome is the one where a stray local database *does* answer and the check passes
    against something that is not the stack. The `Makefile`'s `migrate`/`migrate-down`/
    `check` targets now run through the `migrate` compose service, which is the only one
    holding the table owner's DSN and which resolves `postgres` over the compose network.
    Every `alembic check` claim in §3 that was run from a host venv should be read as
    unverified unless the DSN was overridden; the drift itself is confirmed absent, by
    `make check` against the real database on 2026-08-03.

34. **Deviation (`A0`): `GET /auth/oidc/authorize` and `/callback` answer a browser with
    redirects, not with JSON.** The written spec had `authorize` 401 on an unknown org and
    `callback` return a `TokenResponse` body; three tests asserted exactly that and were
    rewritten. The reason is that both endpoints have exactly one caller and it is a
    **top-level browser navigation** — one from the sign-in form, one from Keycloak — so a
    JSON body is a page of machine-readable text rendered at a person who expected an
    application. There was no way to satisfy `test_signin_error_is_identical_for_unknown
    _org_and_denied_login` on *rendered text* while the failure never reached a rendered
    page, and the callback-denied half (a cancelled Keycloak login) cannot be preflighted
    from the browser at all.
    **Nothing about the disclosure changed.** Every failure produces one identical URL with
    one constant flag — `?error=auth_failed`, not an error code, with deliberately nothing
    to branch on — and `test_every_login_failure_produces_the_same_url` asserts that four
    different causes yield one `Location`. The success path carries **no token in the URL**:
    the callback sets the cookie and the page it lands on exchanges it, because a token in
    a query string is a token in browser history, in the next request's `Referer`, and in
    every proxy log along the way. The redirect target comes from `Settings.web_base_url`
    and never from the request, so it cannot be turned into an open redirect on the one
    route where a credential has just been minted.
    **What this costs:** a non-browser client can no longer read the pair out of the
    callback. Nothing has one — the callback is unreachable without a `state` that only a
    browser round trip produces — and `POST /auth/token` remains JSON for machine callers.

35. **Deviation (`A0`): `GET /auth/me` is pulled forward from `C1`.** `APIContract.md`
    listed it under RBAC. The shell has to name the signed-in user in the sidebar footer
    (`A0` scope item 4) and the access token cannot supply it: it carries `sub`, `org`,
    `sid` and nothing else, by design. Only two other options existed and both are worse —
    put an email in the token, which is exactly the claim discipline `domain/token.py`
    exists to enforce, or ship a placeholder, which C12 forbids.
    It **reports** effective grants and enforces none. The permission matrix is still `C1`,
    and `require_permission(...)` was deliberately **not** written: there is no route to
    apply it to yet, and an unapplied, untested check is the stub §0 rule 5 forbids. The
    reporting is not idle either — it is how
    `test_the_guard_hydrates_roles_from_the_repository_not_the_token` observes hydration at
    the boundary rather than one layer below it, which is the M3.2a lesson.

36. **The cross-tab refresh lock is real but was not exercised with two real tabs.**
    §4 item 26 records that two tabs refreshing at once revoke their own session. `A0`
    solves it with the **Web Locks API**: `navigator.locks.request` serializes the refresh
    across every tab on the origin, and serializing is what makes it safe — tab B waits,
    then refreshes against the cookie tab A has already rotated, so both succeed and no
    token is written anywhere both tabs can read. That last clause is the point; sharing
    the token would mean `localStorage`, which is the thing the whole design avoids.
    **What is unverified:** jsdom has no `navigator.locks`, so the unit tests cover the
    in-tab collapse and the fallback path, and the cross-tab claim rests on the
    specification rather than on an observation. Driving two Playwright pages through a
    simultaneous refresh is the test that would close it, and it needs a way to hold the
    API's `/auth/token` response open on demand. **The fallback is the honest residue:** on
    a browser without Web Locks (Safari before 15.4) the behaviour is exactly what it was
    before — bounded by the in-tab promise, and item 26's hazard intact.

37. **The dev stack has two different "admin" credentials and they are not
    interchangeable.** `mnemos-dev-admin-password` (§3 Environment) is the *internal*
    provider's password for the local `app_user` row `mnemosctl bootstrap` wrote. Keycloak's
    login form wants the **realm** credential from `deploy/keycloak/mnemos-realm.json`,
    which is `admin`. The Playwright run failed for a full minute against the wrong one
    before this was noticed, and the failure looked like a broken login rather than a wrong
    password. Both are dev-stack credentials in the class of Keycloak's own `admin`/`admin`;
    neither is ever to be reused anywhere real. Recorded because the next person to write a
    browser test will reach for the one in the tracker.

38. **The `A0` end-to-end run used a locally-run API and frontend, not the compose
    containers.** `:8010` and `:3100`, against the shared Postgres, Redis and Keycloak. The
    shared `api` and `web` containers still carry the pre-`A0` image and rebuilding them
    would have disrupted work in flight on other branches (the same constraint `M3.4`
    worked under). Two consequences, both temporary: the seeded `identity_provider` row
    names `issuer_internal = keycloak:8080`, which does not resolve from the host, so the
    run used a throwaway org bootstrapped with `localhost` issuers and **deleted
    afterwards** (`SELECT slug FROM org` → `mnemos` only, verified); and the realm client
    needed `http://localhost:8010/...` in `redirectUris` for the duration, **restored and
    verified afterwards**. Nothing about the flow is specific to those ports — CI's
    `compose` job proves the images build and the stack starts — but "it works in the
    shipped containers" is asserted by the compose smoke job and not by the browser run.

39. **`test:e2e` is not in CI, and that is a choice rather than an oversight.** It needs
    Postgres, Redis, a Keycloak with the realm imported, a bootstrapped org and a running
    frontend; CI's `compose` job stands up four of those five and could plausibly host it.
    It is left out because the Playwright browser download plus a real IdP round trip is
    several minutes on every PR, for a suite whose value is highest when a human runs it
    against the stack they are about to demonstrate. The cost is that a regression in the
    login flow is caught by nobody until somebody runs `make` and clicks. **`D1` owns
    moving it into CI**, where an e2e job over the whole stack is already scoped.
    `frontend/e2e/chat.spec.ts` (`A1`) joins `auth.spec.ts` under the same exclusion, for
    the same reason.

40. **The bootstrap admin cannot sign in through Keycloak as itself, and the golden path in
    §3's Environment table used to recommend exactly that.** Found while verifying `A1`
    against this repo's own persistent, already-bootstrapped `mnemos` org rather than the
    throwaway org item 38 used to sidestep it. `mnemosctl bootstrap` creates
    `admin@mnemos.local` as an **internal**-provider `app_user` (password-based,
    `external_subject` NULL). The seeded Keycloak realm *also* has a user named
    `admin@mnemos.local`. Signing in through Keycloak as that realm user reaches
    `TokenService`'s JIT-provisioning path (`M3.4`), which matches on `external_subject` and
    never on email — correctly, per its own docstring — so it finds the internal user
    already holding that email and denies with `"email 'admin@mnemos.local' already belongs
    to a different subject in this org"`. This is the *design* working as intended; the gap
    is that nothing had verified the two seeded "admin" identities collide until a browser
    actually tried both.
    **The practical consequence:** today, only `analyst@mnemos.local`/`analyst` and
    `user@mnemos.local`/`user` — the two realm users bootstrap does not create an internal
    counterpart for — can complete a real Keycloak sign-in against a stack whose `mnemos`
    org has been bootstrapped once. `frontend/e2e/auth.spec.ts` and `chat.spec.ts` both sign
    in as `analyst@mnemos.local` for exactly this reason, and both pass seven-for-seven and
    one-for-one against this repository's actual persistent stack — which is new: before
    this fix, `auth.spec.ts` run against the containers rather than against `A0`'s original
    locally-run API/frontend failed 4 of 7 cases with this same denial.
    **Not fixed at the root, on purpose.** Three real fixes exist — give the bootstrap admin
    a different default email, give the Keycloak realm's demo admin a different email, or
    ship a password-login HTTP endpoint so the internal admin has *any* reachable route (none
    exists today; `InternalProvider` from `M3.2` has no router) — and each is a decision
    about the golden path or the realm seed that deserves its own review rather than a fix
    folded into an unrelated milestone's diff. Recorded here so it is a decision the next
    milestone that touches identity (`C1`) makes on purpose rather than rediscovers.

41. **Nothing in the API process had ever imported the full model registry
    (`mnemos.platform.models`).** `platform/db.py`'s own docstring says every model module
    must be imported there or it "silently disappears from `alembic check`" — true, and it
    obscured that the registry is *also* what makes cross-feature foreign keys resolvable at
    all when the ORM configures its mappers. Every route built before `A1` happened to touch
    only tables whose foreign keys resolve within their own feature's already-imported
    models, so the gap cost nothing until `chat_message.bundle_id`'s `ForeignKey` to
    `context_bundle` (a table `features/context/` owns) was the first one to reach across a
    feature boundary. The failure was `sqlalchemy.exc.NoReferencedTableError`, raised from
    inside a live `SELECT`, not from `alembic check` — which passed throughout, because
    Alembic's own `env.py` already imports the registry correctly and was never what was
    missing. Fixed with one import in `entrypoints/api/main.py`'s composition root, which is
    also the answer for `worker` and `realtime` if either ever gains an ORM path that
    crosses a feature boundary before something else has imported the registry first.

---

## 5. NEXT TASK

### `A3` — ask about your data: NL2SQL with two independent read-only defences

**Do this one only** (rule 9 is suspended for the current run — see the 2026-08-08 note
near the top of this file — but §5 is still rewritten before each milestone, so treat this
as the complete brief regardless of who reads it next).

> **You can now ask a question about your data in English and see the SQL, the rows and
> the narration — and see the guard visibly refuse a write.**

That last clause is half the milestone. **A defence nobody can see is a defence nobody
believes**, so the refusal is a screen a stranger can produce on purpose, not a log line.

**The one architectural rule here, and it is `C1`-adjacent in importance: two independent
defences, neither sufficient alone** (ADAPTATION §9, README "Design decisions worth
defending"). An AST guard that rejects anything but a `SELECT`, *and* execution as
`mnemos_ro`, a Postgres role that physically cannot write. The guard alone is one parser
bug from a write; the role alone gives no useful error and no audit trail of the attempt.
Both, and `test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed` is the test
that proves the second one is really there rather than assumed.

**The warehouse and the role already exist.** `deploy/postgres/init/02-analytics-seed.sql`
seeds a separate `mnemos_analytics` database — 900 `sales_order`, 6 `customer`,
6 `product`, 4 `region` — and creates `mnemos_ro`, whose read-only-ness was proven at `M1`
(`ADAPTATION §8`: `mnemos_ro` INSERT → `ERROR: permission denied for table region`).
`Settings.analytics_database_url` already points at it as `mnemos_ro`, and
`sql_statement_timeout_ms`, `sql_max_rows` and `sql_repair_attempts` are already settings.
None of that is provisional; it was built at `M1` for this milestone.

**Read first, in this order:**

1. §0 through §4 of this file, and the `A2` write-up in §3 — the flow shape (`flows/rag/`),
   the streaming reuse, and the provisional `use_documents` selector are all patterns this
   milestone follows and extends.
2. [`docs/CodingStandards.md`](docs/CodingStandards.md) §9's **mandatory case 4**: "DML
   nested inside a CTE, inside a `UNION`, and inside a subquery is rejected; unparseable
   SQL is rejected fail-closed rather than passed through." Those four are the acceptance
   tests, not suggestions.
3. [`docs/DesignSystem.md`](docs/DesignSystem.md) §3 and §4. New territory: a **result
   grid** (tabular data at the 46rem measure is wrong — the SQL panel and grid want the
   full content column, so decide and write down how) and the **denial state**, which is a
   first-class screen here rather than an error toast.
4. [`docs/ADAPTATION.md`](docs/ADAPTATION.md) §3's `datasources` rows and §6's
   `datasources` schema group — `sql_datasource`, `sql_run` (per-attempt safety verdicts,
   authorized/denied tables) and `glossary_term` all exist from `M2`.
5. **The code you extend:**
   - `backend/src/mnemos/features/datasources/adapters/models.py` — `SqlDatasource`,
     `SqlRun`, `SqlSchemaObject`, `GlossaryTerm`, already specified. Read the comments:
     `sql_run` is designed to record *every attempt* with its verdict, which is what makes
     a refused query auditable rather than merely refused.
   - `backend/src/mnemos/core/types.py` — `SqlVerdict` already enumerates
     `allowed`/`rejected_write`/`rejected_unauthorized_table`/`rejected_unparseable`/
     `rejected_too_complex`, and `check_in` pins the column to it. Use these; do not invent
     a parallel vocabulary.
   - `backend/src/mnemos/flows/rag/` (`A2`) — the flow shape to mirror: a `domain/` of pure
     functions, an `application/` that streams, reusing `A1`'s `ChatModel` port and the
     `AssistantToken`/`AssistantDone`/`AssistantError` events unchanged.
   - `backend/src/mnemos/entrypoints/api/routers/chat.py` — where `use_documents` selects a
     flow today. `A3` adds a second selector in the same provisional shape; `A4` replaces
     both with a classifier.
   - `frontend/src/lib/inspector/SelectionProvider.tsx` (`A2`) — the selection union is
     deliberately named (`{kind: "citation", ...}`) so `A3` can add `{kind: "sql_run", ...}`
     without reshaping it.

**Scope — five deliverables, one commit each.**

1. **Schema introspection.** `features/datasources/`: connect to `analytics_database_url`
   as `mnemos_ro`, read `information_schema` for tables, columns and types, and cache the
   result in `sql_schema_object`. This is the schema *context* the generator is given —
   the model cannot be trusted to guess table names, and a hallucinated table is the
   commonest NL2SQL failure. Refresh is an explicit action, not a per-query cost.
2. **The business glossary.** `glossary_term` rows — "revenue means `sales_order.total_amount`
   summed", "active customer means one with an order in the last 90 days" — fed into the
   same schema context. Seed a handful for the demo warehouse; a CRUD surface for them is
   `C2`-adjacent and out of scope unless the UI slice needs one to be demonstrable.
3. **Generation and the AST guard.** Generate SQL through the `ChatModel` port, then parse
   it with **`sqlglot`** (a new dependency — free, pure-Python, and the alternative is
   hand-rolling a SQL parser, which is the actual security-critical mistake here) and walk
   the AST. Reject anything that is not a single read: `INSERT`/`UPDATE`/`DELETE`/`MERGE`/
   `TRUNCATE`/`DROP`/`ALTER`/`CREATE`/`GRANT`, and reject them **wherever they appear** —
   inside a CTE, inside a `UNION` arm, inside a subquery. Unparseable SQL is rejected
   **fail-closed**, never passed through on the theory that the role will catch it. Every
   attempt writes a `sql_run` row with its `SqlVerdict` and the tables it touched.
4. **Execution and narration.** Execute the allowed statement as `mnemos_ro` with
   `sql_statement_timeout_ms` and a `sql_max_rows` cap, then narrate the result set through
   the model. Persist the assistant message with `flow="nl2sql"` and the `sql_run` id, so a
   later reader can open the answer and find the exact statement that produced it.
   `sql_repair_attempts` exists for the "the model wrote invalid SQL, tell it the error and
   let it try once more" loop — bounded, and every attempt gets its own `sql_run` row.
5. **The SQL panel.** In the chat surface: the generated SQL (monospace, syntax-plain is
   fine), the result grid, and the narration. **And the refusal**, as a real state: when
   the guard rejects, the screen shows the SQL it refused and the verdict in plain words —
   "this would have written to `sales_order`; Mnemos only reads" — not a generic error.
   That screen *is* deliverable 5's reason to exist.

**Acceptance**

- `test_dml_is_rejected_inside_a_cte_a_union_and_a_subquery` — three cases, one test name,
  CodingStandards §9 case 4. A guard that only checks the statement's top-level type passes
  a naive test and fails this one, which is the whole point.
- `test_unparseable_sql_is_rejected_fail_closed`.
- `test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed` — the second defence,
  proven independently by executing a write **directly** as `mnemos_ro`, bypassing the
  guard entirely. Without this the two-defence claim rests on one of them.
- `test_a_select_is_allowed` — the control. A guard that refuses everything passes all four
  above.
- `test_every_attempt_writes_a_sql_run_row_with_its_verdict` — including the refused ones,
  because an audit trail that only records successes is not one.
- `test_a_query_against_another_orgs_datasource_is_a_404`.
- `test_the_result_set_is_capped_at_sql_max_rows`.
- `test_a_statement_that_exceeds_the_timeout_is_cancelled_not_left_running`.
- **Frontend:** `test_the_sql_panel_shows_the_statement_the_grid_and_the_narration`.
- **Frontend:** `test_a_refused_query_shows_the_verdict_and_the_sql_it_refused`.
- **Frontend:** `test_the_sql_panel_has_no_axe_violations`.
- **Playwright**, extending `frontend/e2e/`: sign in as `analyst@mnemos.local` (§4 item
  40), ask "what was revenue by region last quarter", see SQL + grid + narration. Then
  provoke a refusal and see it named on screen. Skips loudly with the stack down; cleans up
  after itself like `knowledge.spec.ts` does.
- **Gates:** `make test` above 278 · `make lint` · `make types` clean · `make check` clean
  (**a migration may genuinely be needed here** if `sql_run` lacks a column the flow wants
  — unlike `A1` and `A2`, that would be legitimate; say so in §4 and write a reversible
  revision) · frontend `lint`, `tsc --noEmit`, `test`, `build` · **CI green, all jobs.**

**Watch out for these:**

- **Do not let the AST guard be the only defence, and do not let `mnemos_ro` be the only
  one either.** The first is one parser bug from a write; the second gives an unhelpful
  Postgres error and no audit trail. Both, always, and the test above proves the second
  independently.
- **`sqlglot` must parse with the Postgres dialect**, or it will accept syntax Postgres
  rejects and reject syntax Postgres accepts — either way the guard is reasoning about a
  different language than the one that will execute.
- **The analytics database is a separate connection, not `Database`.** `Database` is the
  application's own Postgres as `mnemos_app`. `mnemos_analytics` as `mnemos_ro` is a second
  engine with its own pool and its own statement timeout, and mixing them would put the
  warehouse query inside a transaction holding RLS state for the app database.
- **Never interpolate the model's SQL into another statement.** It is executed as-is, once,
  after the guard — string-building around it (adding a `LIMIT` by concatenation, say) is
  how a guarded statement becomes an unguarded one. Cap rows by fetching at most
  `sql_max_rows + 1` from the cursor instead.
- **`alembic check` from a host venv talks to the wrong Postgres** (§4 item 33) — `make
  check`, always. **`ruff format` is version-sensitive** (§4 item 22) — `make lint`.
- **Sign in as `analyst@mnemos.local` in browser evidence** (§4 item 40).

**Explicitly not in `A3`:** the router that chooses NL2SQL without being told (`A4` — this
milestone ships a second provisional selector beside `use_documents`), a datasource
registry UI or a second warehouse dialect (the `SqlDialect` port makes that a config
exercise; Postgres only, ADAPTATION §3), the cost ledger for generated queries (`C2`), and
the context compiler (`C4`).

### Then, in order — the phase tables in §3.0 are the plan

Each row there is one session, and each carries its own "you can now ___" (C14). The next
few, so the shape is visible without scrolling back:

- **`A3` — ask about your data.** Specified in full above; this is the task.
- **`A4` — stop choosing a mode.** Classify each message to chat / RAG / NL2SQL and show
  which flow answered and why. This is also where the two provisional selectors — `A2`'s
  `use_documents` and `A3`'s NL2SQL equivalent — are replaced by a real classifier, and
  both were written down as provisional precisely so this milestone knows what to remove.

Then Phase B (`B1`–`B4`), Phase C (`C1`–`C4`), Phase D (`D1`) — §3.0.

**Commit shape:** one commit per numbered deliverable, not one per milestone. A backend
deliverable and its UI slice may share a commit or be adjacent commits — never adjacent
*milestones* (C12).

---

## 6. Blockers

*None.*

---

## 7. Update protocol

When you finish a task, in the **same commit**:

1. Move it from §5 to §3, or add it to §4 if it revealed a new weakness.
2. Rewrite §5 to fully specify the next task at the same level of detail — the next
   agent may have no context beyond this file.
3. Update the header (`Last updated`, `Phase`, `Next task`, `Branch`).
4. **Update `docs/ADAPTATION.md` too** — §7 milestone position and §8 current state, with
   the evidence (commands run, output observed) rather than a claim that it works.
5. If benchmark numbers moved, update the README **and** `bench_results/*.json`.
6. If you deviated from a documented design, say so explicitly in §4. An undocumented
   deviation is the most expensive thing to discover later, because the docs will be
   trusted and will be wrong.
7. **State what the UI slice was** (C12). If a milestone shipped without one, §4 must say
   which screen is missing and why — "the backend landed and the UI is next milestone" is
   the drift this rule exists to prevent, so it needs to be written down rather than
   assumed.
8. **If you added a design token or a component, update
   [`docs/DesignSystem.md`](docs/DesignSystem.md) in the same commit** — including the
   measured contrast row for any new colour (§2.1). A token that exists only in code is a
   token the next agent will duplicate under a different name.
9. Push the branch and make sure its PR exists.
