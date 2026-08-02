# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It states what is built, the constraints
> you must not violate, and the exact next task. When you finish work, update this file
> **and [`docs/ADAPTATION.md`](docs/ADAPTATION.md)** *in the same commit* — a stale
> tracker is worse than none.

**Last updated:** 2026-08-02
**Phase:** **A — make it a chatbot.** The foundation (stack, schema, tenant isolation,
identity, app shell, CI) is built; the product surface is not
**Next task:** `A0`, fully specified in §5. Take them one at a time, in order
**Branch:** `feat/a0-auth-surface`. **`main` contains M1+M2 (PR #1), M3.1–M3.3 (PR #2),
the slice plan (PR #3), CI (PR #4), M3.7 bootstrap (PR #5), F0 the app shell, and M3.4's
backend half**

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
| **A0** | Sign-in screen + browser session handling (M3.4's UI half) + the fail-closed route guard (deny by default, from old `M3.6`) | **sign in through Keycloak, stay signed in across a reload, and sign out** — and no route added after this is reachable unauthenticated | ⬜ **next** |
| **A1** | LLM gateway (Ollama) · chat sessions + messages · SSE streaming · the chat surface | **talk to it** — ask a question and watch the answer stream in token by token | ⬜ |
| **A2** | Upload → extract → chunk → embed (pgvector HNSW) · retrieval ported from `_v1` · RAG flow · citations · knowledge library | **upload a document and ask questions about it**, with citations you click into | ⬜ |
| **A3** | NL2SQL: introspection · glossary · generate · AST read-only guard · `mnemos_ro` execution · narration · SQL panel | **ask a question about your data in English** and see the SQL, the rows and the narration — and see the guard visibly refuse a write | ⬜ |
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
| Stack up | `docker compose up -d` (add `--profile web` from M13) |
| Schema report | `docker compose exec api mnemosctl db doctor` |
| Migrations | `cd backend && alembic upgrade head \| downgrade base \| check` |
| Tests | `cd backend && ../.venv/bin/python -m pytest` → **105 passed** (needs Docker + Keycloak; see §4.8) |
| Fast tests | everything except `test_tenant_isolation.py` and `test_bootstrap.py` → no Docker. The 2 live-Keycloak tests skip cleanly when the stack is down |
| First-run setup | `mnemosctl bootstrap --org-slug <slug> --org-name <name> --admin-email <addr>`, password from `MNEMOS_BOOTSTRAP_ADMIN_PASSWORD` or the prompt. Idempotent; re-running is safe |
| Bootstrapped locally | org `mnemos` / admin `admin@mnemos.local` / password `mnemos-dev-admin-password` — a **dev-stack credential**, in the same class as Keycloak's `admin`/`admin` and MinIO's `mnemos-dev-secret`, and never to be reused anywhere real |
| Type check | `../.venv/bin/mypy --strict src/mnemos/core src/mnemos/features` — the 4 files that still fail project-wide `mypy` are all in the quarantined `_v1/` |
| DB roles | `migrate` connects as `mnemos` (owner). api/worker/realtime connect as `mnemos_app` |
| Host ports | postgres `15432`, redis `6380`, api `8000`, realtime `8001`, keycloak `8080`, minio `9000/9001`, ollama `11434` |
| UI, such as it is | Swagger `http://localhost:8000/docs` · Keycloak `:8080` (`admin`/`admin`) · MinIO `:9001` (`mnemos`/`mnemos-dev-secret`). No app frontend until M13 — see §4.11 |
| Git identity | `Cheella Sree Harsha <cheellasreeharsha2803@gmail.com>` (repo-local) |
| GitHub | `Harsha2803/mnemos`, private. **Two accounts in `gh`; keep `Harsha2803` active** |

---

## 4. Known gaps and honest weaknesses

Recorded so they are not rediscovered as surprises:

1. **Answer retention is a tie under a good embedder** (100% vs 100%). The corpus is
   5.4k tokens — too small for budget pressure to bite. Growing the corpus 10× is the
   single highest-value change to the *benchmark*; deferred until after the M4 port so
   it is measured once, on Postgres, rather than twice.
2. **Duplicate waste rises at large budgets** (14% at 3000) because more
   near-threshold content is admitted. Dedup is a threshold, not a guarantee.
3. **Brute-force cosine over all chunks** on every query in `_v1`. Fine at 56 chunks,
   `O(n)` and wrong at 100k. The HNSW indexes exist in the schema as of M2; wiring the
   scan to use them is M4.
4. **`all_chunks()` reloads the whole corpus per operator call** — three times per
   compile. Obvious caching win, deliberately not done in `_v1` because it is thrown
   away at M4.
5. **No LLM in the loop yet.** The v0.1 benchmark measures *what reaches the model*, not
   answer correctness. Ollama is now running, so an LLM-in-the-loop arm becomes possible
   from M7 — but it must not replace the deterministic metrics.
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
    CHECK exist; the compiler that fills them is M4.
11. **The frontend is still an empty directory** and `web` is still behind a compose
    profile — but this is now the **next task**, not a deferred milestone. `F0` builds the
    shell and un-gates the service; see §3.0 for why `M13` was dissolved. Until `F0` lands
    the only UI is Swagger at `http://localhost:8000/docs`, the Keycloak console at `:8080`
    (`admin`/`admin`) and the MinIO console at `:9001`.
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
14. **`ThreatModel.md` §5 (EdDSA) still contradicts `core/config.py` (HS256).** Untouched
    by M3.2 and M3.3, neither of which issues a token. **`M3.4` must pick one and reconcile
    both documents in the same commit** — see §5.
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
17. **The OIDC callback returns a subject, not a token.** Deliberate — `M3.4` replaces the
    response with an access/refresh pair. Until then there is no way to *stay* logged in,
    only to prove a login happened.
18. **There is no CI. `.github/workflows/` does not exist**, so `gh pr checks` reports
    nothing and "the PR is green" has, so far, meant *someone ran the gate locally and said
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
    two-line fix whenever that file is next touched; `_v1/` is fixed by the M4 port.
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
    the change. Nothing depends on this yet because M3.6's guard does not exist, but it
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

---

## 5. NEXT TASK

### `A0` — the auth surface: sign in, stay signed in, and close every door behind you

**Do this one only.** It is the last piece of identity that Phase A actually needs, and it
is what makes every milestone after it safe to build. It has three parts and they belong
together: without the screen nobody can sign in, without session handling nobody stays
signed in, and without the guard every route `A1` adds is open to the world.

**Why this and not straight to chat.** `M3.4`'s backend half issues tokens that nothing
presents; `frontend/` has a shell with no way in. Building the chat surface first would
mean building it unauthenticated and retrofitting a principal through every handler — the
retrofit that fails closed in tests and fails open in production. One session now removes
that risk permanently.

**Read first:** [`docs/DesignSystem.md`](docs/DesignSystem.md) §4 (forms, destructive
actions, empty states) and §3 (accessibility floors); the M3.4 entry in §3 of this file for
the token shape, the cookie, and the rotation semantics; `docs/APIContract.md` §1–§2;
`backend/src/mnemos/entrypoints/api/routers/auth.py` and
`backend/src/mnemos/features/identity/application/tokens.py`.

**Scope.**

1. **The fail-closed route guard.** A FastAPI dependency that resolves the bearer access
   token to a `Principal` (hydrating roles and tags from the repository — *not* from the
   token, see M3.4's `test_access_token_carries_no_roles_or_permissions`), installed so that
   **a route with no explicit decoration is authenticated by default**. Deny by default is
   the whole point: the acceptance test is
   `test_unauthenticated_request_is_denied_by_default` **on a route that declares no guard
   at all**, added specifically for the test. Public routes (`/healthz`, `/readyz`, `/`,
   the auth endpoints, `/docs`, `/openapi.json`) are an explicit, enumerated allow-list —
   never a prefix match, because a prefix match is one careless route name away from
   exposing everything under it.
   *Not in scope:* the permission matrix. `require_permission(...)` may exist and be
   applied where obvious, but the full RBAC role/permission surface is `C1`.
2. **The sign-in route.** Org slug field, then "Continue with Keycloak" driving
   `GET /api/v1/auth/oidc/authorize?org=…`. Real `<form>` semantics, one `filled` button,
   `aria-live` on the error. **Every failure renders the same message.** The backend
   already guarantees one constant denial string and M3.4 proved the wire carries no
   distinguishing detail; the UI must not undo that by branching on a status code to say
   "no such org". That is the M3.2a mistake one layer further out.
3. **Session handling.** Access token in memory only — never `localStorage`, which any XSS
   can read. Refresh token in the `httpOnly` cookie the API already sets. A TanStack Query
   interceptor refreshes once on a 401 and, on a second 401, clears state and returns to
   sign-in. **Concurrent 401s must trigger exactly one refresh**, not one per in-flight
   request: rotation treats a second use of the same refresh token as theft and kills the
   family, so a naive interceptor logs the user out every time two requests race. Note §4
   item 23 — two open tabs are the same hazard, and this is where it is solved or shipped.
4. **The protected shell.** `F0`'s layout behind an auth boundary. An unauthenticated visit
   redirects to sign-in **preserving the intended destination**. Sign-out calls
   `POST /v1/auth/token:revoke` and clears the cookie. The signed-in user's email and org
   appear in the sidebar footer — the shell currently renders a placeholder identity, and
   this is where it becomes real.

**Acceptance**

- `test_unauthenticated_request_is_denied_by_default` — on a route with **no** explicit
  guard. This is the one that matters; write it first and watch it fail.
- `test_a_route_in_the_public_allowlist_is_reachable_without_a_token` — the control, so the
  guard is not passing by refusing everything.
- `test_concurrent_401s_trigger_exactly_one_refresh` — frontend. Fire N requests, stub two
  401s, assert exactly one call to the refresh endpoint.
- `test_signin_error_is_identical_for_unknown_org_and_denied_login` — frontend, asserting
  the rendered text, not the network layer.
- `test_signout_revokes_the_refresh_family_and_clears_the_cookie`.
- **A Playwright run against the live Keycloak**: sign in as the seeded admin, land on the
  shell, reload and stay signed in, sign out, confirm the protected route bounces back to
  sign-in. This closes M3.4's "could not verify" — the Keycloak login *form* was never
  driven, because `httpx` cannot satisfy Keycloak 26's browser-session requirements and a
  browser can. Make it skip cleanly when the stack is down, and **verify it skips** by
  stopping the stack rather than assuming.
- `pytest` green, `ruff` + `mypy --strict` clean, `alembic check` clean (no migration).
  Frontend: `tsc`, ESLint, `axe`, `npm run build` clean. **CI green on the PR** — this is
  now a real check, not a pasted local gate.

**Prerequisite, already satisfied:** `M3.7` seeded org `mnemos` with `admin@mnemos.local`
and both provider rows, so there is something to sign in *as*. See §3.

**Explicitly not in `A0`:** the permission matrix, API keys, an org switcher, user
management screens. All `C1`.

### Then, in order — the phase tables in §3.0 are the plan

Each row there is one session, and each carries its own "you can now ___" (C14). The next
few, so the shape is visible without scrolling back:

- **`A1` — talk to it.** LLM gateway over Ollama behind a port (the model is swappable and
  the benchmark depends on it staying so), `chat_session` + `chat_message` persistence, an
  SSE streaming endpoint, and the chat surface: composer, message list, **token-by-token
  rendering — never a spinner over a blank region** (DesignSystem §4), session list in the
  sidebar. No retrieval yet; it answers from the model alone, and that is a complete
  milestone because you can talk to it.
- **`A2` — ask about your documents.** Upload to MinIO, extract, chunk with char offsets
  retained, embed, and **port `_v1`'s retrieval onto pgvector HNSW** — the port lands here
  rather than in its own milestone precisely so retrieval is not written twice (§3.0's
  mapping table). Then the RAG flow and citations that click through. §4 item 3 (brute-force
  cosine) is discharged here.
- **`A3` — ask about your data.** Introspect `mnemos_analytics`, glossary terms, generate
  SQL, **AST read-only guard plus the `mnemos_ro` role** as two independent defences, execute,
  narrate. The UI shows the SQL, the grid and the narration — and shows the guard refusing a
  write, because a defence nobody can see is a defence nobody believes.
- **`A4` — stop choosing a mode.** Classify each message to a flow and show which one
  answered and why.

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
