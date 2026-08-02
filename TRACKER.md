# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It states what is built, the constraints
> you must not violate, and the exact next task. When you finish work, update this file
> **and [`docs/ADAPTATION.md`](docs/ADAPTATION.md)** *in the same commit* — a stale
> tracker is worse than none.

**Last updated:** 2026-08-02
**Phase:** **M3 — identity, in vertical slices.** `F0` ✅ (the app shell is live at
`http://localhost:3000`); backend is at `M3.3`; `M3.4`–`M3.7` remain and each carries a UI
slice (§5)
**Next task:** `M3.4` — platform JWT + refresh rotation **and the sign-in screen**, fully
specified in §5. Take them one at a time, in order
**Branch:** `feat/f0-frontend-foundation`. **M1+M2 merged as PR #1; M3.1–M3.3 merged as
PR #2 (`98fe47a`); F0 on this branch** — `main` contains everything through the OIDC
round trip

> **2026-08-02 — the project is now built in vertical slices.** Every milestone ships its
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
   architecture, the JIVA capability map, the schema plan, and the M1–M14 ledger.
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

## 0.1 SCOPE CHANGE — read this before anything else

The project was reframed on 2026-07-26. v0.1 was a **benchmark harness with a prompt-diff
viewer** — an engine and a lab bench, not a product. That was a misread of the goal.

**What is actually wanted:** a **chatbot** that does many things — RAG over documents,
NL2SQL over a database, MCP tools, auth, ingestion from cloud sources — where governed
memory and compiled context are the feature that *stands out among* those, not the whole
app.

The full plan, the JIVA capability map, the schema and milestones M1–M14 live in
**[`docs/ADAPTATION.md`](docs/ADAPTATION.md)**. Read that next.

The v0.1 kernel is preserved in `backend/src/mnemos/_v1/` and is ported (not rewritten)
in milestone M4.

## 1. What this is (30 seconds)

**Mnemos — an AI workspace chatbot whose context is a compiled artifact.**

One conversation surface. A router decides whether an answer needs documents (RAG), a
database (NL2SQL), a tool (MCP), memory, or a combination. Underneath, every message has
an inspectable context bundle and a governed memory layer that distinguishes current
facts from superseded ones.

**Headline measured result, v0.1 kernel** (neural embedder, 800-token budget, 23
questions): naive quoted a **superseded policy revision in 100% of prompts**; compiled,
**0%**. Superseded memory facts: 61% → 0%. Restricted-content leak: 13% → 0%. Duplicate
token waste: 6.9% → 1.1%. Answer retention: 100% both. Latency: 69 ms → 81 ms.

**These numbers were measured on SQLite** and must be re-run after the M4 port.

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
| C11 | **Never copy from `jiva/`.** Patterns are portable; artifacts are not. | See ADAPTATION §2. Employer IP in a public repo is a real legal problem |
| C12 | **Every feature ships its UI in the same milestone.** Backend and frontend advance together; no milestone is complete with an untouched `frontend/`. | A capability with no screen is one nobody has exercised end to end. It also hides integration defects — M3.2a was a leak invisible to every unit test because nothing looked at the wire |
| C13 | **The UI follows [`docs/DesignSystem.md`](docs/DesignSystem.md).** Tokens are the only source of colour, type, spacing and radius. | Consistency is the whole value of a design system; one component with a hard-coded hex is the crack it starts leaking through. The system draws its *ideas* from Apple's design resources — type scale, spatial rhythm, materials, motion character — but the palette, accent and identity are Mnemos's own; §0 there records which Apple assets are off-limits and why |

---

## 3. Current state — what is actually built

Milestone ledger and exit criteria live in [ADAPTATION §7](docs/ADAPTATION.md#7-milestones).
Detailed evidence for each ✅ is in [ADAPTATION §8](docs/ADAPTATION.md#8-current-state).

### 3.0 The slice plan — every milestone has two halves

`M13` ("Next.js frontend, all pages") **no longer exists.** Building every screen at the
end meant the screens would be designed against APIs shaped without them, and would land
as one unreviewable drop. Its contents are now distributed: a foundation task (`F0`) plus
a UI slice attached to each milestone that produces something a user can see.

**Read the frontend column as part of the milestone, not as a follow-up.** A milestone is
complete when both halves are (C12).

| ID | Backend half | Frontend half | Status |
|---|---|---|---|
| **M1** | Container stack, backend skeleton | — (no UI to build yet) | ✅ |
| **M2** | Alembic + 41-table schema | — | ✅ |
| **F0** | — | **App shell**: Next.js, design tokens, three-column layout, theming, base primitives, generated API client | ✅ |
| **M3** | identity: ~~`3.4` JWT~~ ✅ · `3.5` API keys · `3.6` RBAC · ~~`3.7` bootstrap~~ ✅ | **Sign-in screen**, session handling, protected shell, API-key management, org switcher (`3.7` has no UI half — see §5) | 🟡 `3.1`–`3.4` + `3.7` ✅ backend; the UI half lands on F0's shell |
| **M4** | port memory/retrieval/context kernel to PG | **Context inspector** — the bundle viewer. The signature screen of the product | ⬜ |
| **M5** | objectstore (MinIO) + connectors + Redis Streams | **Sources**: connect a source, browse it, watch events arrive | ⬜ |
| **M6** | knowledge: extract, chunk, embed, ingest jobs | **Knowledge library** + upload + live job progress | ⬜ |
| **M7** | LLM gateway (Ollama) + prompt store + cost ledger | **Prompt manager** (versions, activate) + **cost dashboard** | ⬜ |
| **M8** | chat: sessions, messages, SSE streaming | **The chat surface.** Streaming, folders, bookmarks, feedback | ⬜ |
| **M9** | RAG flow + citations | **Citations** in the message, click-through into the inspector | ⬜ |
| **M10** | NL2SQL: introspection, AST guard, narration | **SQL panel**: generated SQL, result grid, narration | ⬜ |
| **M11** | MCP tool runtime | **Tool console** + approval dialogs for gated calls | ⬜ |
| **M12** | router: classify → flow | **Flow indicator** on each message, and why it was chosen | ⬜ |
| **M13** | ~~Next.js frontend~~ | **dissolved** into `F0` + the slices above | — |
| **M14** | realtime WS, nginx, e2e, docs | **Live streaming/presence** polish; Playwright e2e over the whole stack | ⬜ |

**Why `F0` came before `M3.4`.** `frontend/` was an empty directory: there was nothing for
a sign-in screen to be built *in*. `F0` was the one task with no backend half, because it
is the scaffolding every later UI slice lands on. It is done; from `M3.4` the pattern is
uniform.

### ✅ F0 — the frontend foundation, verified 2026-08-02

`frontend/` is no longer an empty directory. A running, themed, accessible three-column
shell with **no feature screens**, and `docker compose up -d` now brings it up with
everything else. It is the scaffolding every later UI slice lands on, so the parts that
would be expensive to retrofit across forty components — tokens, theming, the hit-target
floor, the generated client — are the parts it spends its effort on.

| File | What it is |
|---|---|
| `frontend/src/app/globals.css` | Every token from DesignSystem §2, and **the only file in the frontend allowed to contain a colour**. Wired into Tailwind v4 through `@theme inline`; `--color-*: initial` deletes Tailwind's own palette, which is the half that makes C13 enforceable — `bg-red-500` contains no hex literal and would otherwise sail past the grep |
| `frontend/src/lib/theme.ts` | Three preferences, not two. `THEME_INIT_SCRIPT` is a blocking inline script in `<head>`; "system" *removes* `data-theme` so the media query governs again. A module store read through `useSyncExternalStore`, because the value is written by a script that ran before React existed on the page |
| `frontend/src/components/shell/AppShell.tsx` | The three columns. Below 1024px the inspector becomes a Radix Dialog and below 768px the sidebar does too — a change of *component*, not of width, which is why the breakpoints are read in JS |
| `frontend/src/components/ui/` | `Button` (three ranks, no fourth), grouped-inset `List` with separators inset to the text origin, `EmptyState`, `Skeleton`. Each queried in its test by role and accessible name |
| `frontend/src/lib/api/schema.ts` | Generated by `openapi-typescript` from the live `/openapi.json` and committed. `npm run generate:api` regenerates it. Nothing hand-written |
| `frontend/src/lib/api/readiness.ts` | The one real call. `"/readyz"` is checked against the generated `paths`, so a renamed endpoint is a compile error rather than a 404 on screen |
| `frontend/src/test/harness.ts` | jsdom's CSS parser predates cascade layers and drops every rule inside one — most of the sheet. Flattening the layer wrappers is what lets a test call `getComputedStyle` and get the value a browser would |
| `frontend/Dockerfile` | Three stages mirroring `backend/Dockerfile`; `output: "standalone"`, uid 10001, no toolchain in the runtime image |
| `docker-compose.yml` | `profiles: ["web"]` deleted, healthcheck added, and `x-web-env` used as **both** `build.args` and `environment` — a NEXT_PUBLIC value is inlined into the browser bundle at build time, so supplying it only at runtime reaches the server and never the browser |

**Evidence against the live stack and a real browser** (headless Chrome over CDP, not
jsdom — the two things jsdom cannot evaluate are `prefers-color-scheme` and layout):

```
docker compose ps        api keycloak minio ollama postgres realtime redis worker
                         all Up, and  web  Up 22 seconds (healthy)
curl -o /dev/null -w '%{http_code}' http://localhost:3000        ->  200

measured in Chrome, emulating each OS preference:
  dark OS,  no choice   ->  data-theme=null    body bg rgb(11, 11, 15)
  dark OS,  chose light ->  data-theme=light   body bg rgb(255, 255, 255)
  light OS, chose dark  ->  data-theme=dark    body bg rgb(11, 11, 15)
  light OS, no choice   ->  data-theme=null    body bg rgb(255, 255, 255)
  sidebar 260px · inspector 320px · .measure 736px (= 46rem) · health "API ready"
  at 900px wide: inspector absent from the layout;  at 600px: sidebar absent too

curl -H 'Origin: http://localhost:3000' http://localhost:8000/readyz
  access-control-allow-origin: http://localhost:3000
  {"status":"ready","checks":{"postgres":"ok","redis":"ok"}}
built browser chunk contains  http://localhost:8000  and  "/readyz"
--dump-dom after JS ran       "API ready" · "postgres" · "redis"
```

That last pair is the end-to-end proof asked for in F0.7: the container, the CORS
configuration, the generated types and the query layer each worked alone before this.

**No flash of the wrong theme, and it was watched rather than assumed.** With
`prefers-color-scheme: dark` emulated and `mnemos.theme = "light"` stored, a CDP
screencast over a hard reload captured 13 frames; **the first painted frame is already
light**, with the toggle showing Light selected. A dark first frame is exactly what a
deferred script produces, so this is the observation the acceptance criterion wanted.

| Check | Result |
|---|---|
| `npm run test` (Vitest) | **41 passed**, 6 files, 5.5s |
| `npx tsc --noEmit` | clean, `strict` plus `noUncheckedIndexedAccess` |
| `npm run lint` (ESLint 9, `next/core-web-vitals` + `next/typescript`) | clean |
| `npm run build` | clean; `/` 1.99 kB, 119 kB first load |
| `npm audit` | **0 vulnerabilities** — Next 15 pulls a vulnerable `postcss` and `sharp` transitively, both pinned forward with `overrides` |
| axe (`vitest-axe`) on the shell | **0 violations** |
| `pytest` (backend) | **97 passed** — F0 changes no Python (`git diff origin/main...HEAD -- '*.py'` is empty) |
| `alembic check` | "No new upgrade operations detected" |

The acceptance tests are named as asked: `test_theme_toggle_overrides_the_system_preference_in_both_directions`,
`test_every_interactive_target_is_at_least_44px` (twice — over the primitives and over the
whole shell), `test_no_component_hardcodes_a_colour`,
`test_reduced_motion_collapses_every_transition_and_animation`, and
`test_the_shell_has_no_axe_violations`.

Three tests are worth keeping deliberately, because a later reader might take them for
padding:

- `test_every_token_in_the_design_system_is_defined_in_globals_css` parses DesignSystem §2
  and fails on any token the CSS does not define. A token that is documented but missing is
  a literal waiting to be written, which is the exact leak C13 exists to stop.
- `test_the_two_dark_palettes_declare_the_same_tokens`. CSS cannot share one declaration
  block between a media query and a selector, so the dark palette is written twice. Drift
  between the copies is one subtly wrong shade in exactly one mode — the kind of defect
  nobody reports — so it is made a test failure instead.
- `test_the_three_ranks_are_visually_distinct_and_there_is_no_fourth` computes the three
  button backgrounds and fails if any two collapse. Three ranks resolving to one fill is
  one rank with three names, and nothing else in the suite would notice.

**Not done here, deliberately:** no sign-in form, no chat UI, no inspector *content* — the
inspector renders an `EmptyState` until M4 fills it. No Playwright either; `M3.4` owns it,
and it is the right milestone for it because that is the first flow that crosses the API.

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
reuse. The UI slice (items 7–9 in §5) is still open — see §4 item 20.

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
| Tests | `cd backend && ../.venv/bin/python -m pytest` → **183 passed** (needs Docker + Keycloak; see §4.8) |
| Fast tests | everything except `test_tenant_isolation.py` and `test_session_store.py` → **167 passed in 5.5s**, no Docker. The 2 live-Keycloak tests skip cleanly when the stack is down |
| First-run setup | `mnemosctl bootstrap --org-slug <slug> --org-name <name> --admin-email <addr>`, password from `MNEMOS_BOOTSTRAP_ADMIN_PASSWORD` or the prompt. Idempotent; re-running is safe |
| Bootstrapped locally | org `mnemos` / admin `admin@mnemos.local` / password `mnemos-dev-admin-password` — a **dev-stack credential**, in the same class as Keycloak's `admin`/`admin` and MinIO's `mnemos-dev-secret`, and never to be reused anywhere real |
| Type check | `../.venv/bin/mypy --strict src/mnemos/core src/mnemos/features src/mnemos/entrypoints` — clean on everything M3 has touched; what still fails project-wide is listed in §4 item 19 |
| DB roles | `migrate` connects as `mnemos` (owner). api/worker/realtime connect as `mnemos_app` |
| Host ports | postgres `15432`, redis `6380`, api `8000`, realtime `8001`, keycloak `8080`, minio `9000/9001`, ollama `11434` |
| UI | **The app shell at `http://localhost:3000`** (F0). Also Swagger `http://localhost:8000/docs` · Keycloak `:8080` (`admin`/`admin`) · MinIO `:9001` (`mnemos`/`mnemos-dev-secret`) |
| Frontend gate | `cd frontend && npm ci && npm run lint && npx tsc --noEmit && npm run test && npm run build` → **41 tests pass**, all four clean |
| Regenerate API types | `cd frontend && npm run generate:api` against a running api. `src/lib/api/schema.ts` is committed and never hand-edited |
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
11. ~~**The frontend is still an empty directory.**~~ **Discharged by `F0`, 2026-08-02.**
    The shell is at `http://localhost:3000`, `web` is un-gated and healthy in
    `docker compose ps`, and the evidence is in §3. What remains missing is *screens*, not
    scaffolding: there is no sign-in form (M3.4), no chat surface (M8) and no inspector
    content (M4), and each is named against the milestone that owns it rather than left
    implied.
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
    (M11), an external audit consumer, or tokens crossing an organisational boundary. At
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

24. **C12 is not satisfied for `M3.4`: the backend landed without its UI slice.** Written
    down rather than implied, because "the backend landed and the UI is next" is exactly
    the drift C12 exists to prevent. The reason is sequencing and it is not an excuse
    that generalises: `frontend/` was an empty directory, so `F0` (the app shell) had to
    exist before a sign-in screen could be built *in* anything. **`F0` has since landed**
    (§3), so the blocker is gone and items **7–9 of §5 `M3.4`** are the outstanding work,
    fully specified there. Until they land, the only way to exercise a login end to end is
    by hand or through the test suite.

25. **The refresh window slides; there is no absolute session lifetime.** Every rotation
    sets `expires_at = now + refresh_token_ttl_s`, so an actively used session never
    reaches an end — fourteen days is an *idle* timeout, not a maximum. Capping it needs
    the chain root's `issued_at`, which means either a walk to the root on every refresh or
    a `family_id` column and a migration. Neither is worth doing until a policy asks for
    it. Pinned by `test_the_refresh_window_slides_on_every_rotation` so it stays a decision
    somebody made rather than one nobody noticed.

26. **A user who deliberately opens two tabs mid-refresh revokes their own session.** This
    is the cost of treating a lost compare-and-set as reuse, and it is the right trade —
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
    It is a five-line change and `M3.4`'s remaining frontend half is the natural moment.
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
    §3 M3.2a). Playwright, at `M3.4`'s frontend half, is where this stops being a bespoke
    script.
31. **The frontend has no `mypy`-equivalent gate on the generated client's *runtime*
    shape.** `schema.ts` guarantees the types the API *documents*; it guarantees nothing
    about the body the API actually sends, and for `/readyz` it documents nothing at all
    (item 20). `parseReadiness` closes that for one endpoint by hand. If a third or fourth
    endpoint needs the same treatment, that is the signal to add a runtime validator
    generated from the schema rather than to write a third narrowing function.

---

## 5. NEXT TASK

> `F0` landed on 2026-08-02 — the app shell, the design tokens and the generated client
> are in `frontend/`, and the evidence is in §3. Every task below now ships **both** halves
> (C12), and the frontend half lands on F0's shell rather than inventing its own.

### `M3.4` — platform JWT + refresh rotation, **and the sign-in screen**

**Backend half: ✅ done 2026-08-02** (branch `feat/m3.4-platform-jwt`, PR #6). Evidence in
§3. **Frontend half: still open** — items 7–9 below are the remaining work, and §4 item 20
records that C12 is unsatisfied until they land.

1. ~~**Settle the algorithm conflict first.**~~ ✅ **HS256**, argued in `ThreatModel.md`
   §5.1 and reconciled with `core/config.py` in the same commit. §4 item 14 carries the
   decision and what would reverse it.
2. ~~**Access tokens**, 15 min, identity only — no roles, no permissions, no tags.~~ ✅
   Claims are exactly `sub`, `org`, `sid`, `iat`, `exp`, `iss`, `jti`, and
   `FORBIDDEN_CLAIMS` is enforced when minting *and* when verifying.
3. ~~**Refresh tokens**: high-entropy from `secrets`, SHA-256 via `digest_token`,
   compared with `tokens_equal`.~~ ✅
4. ~~**Rotation and the family kill.**~~ ✅ Plus the case the spec did not name: **losing
   the compare-and-set counts as reuse too**, because two concurrent presentations of one
   token would otherwise produce two live chains from one credential.
5. ~~**The org travels in the credential**: `<org_slug>.<secret>`.~~ ✅ `APIContract.md`
   §1 updated, and the slug is hashed *with* the secret so it binds rather than hints.
6. ~~Replace the callback's `SubjectResponse` with the token pair; `POST /v1/auth/token`
   and `POST /v1/auth/token:revoke`.~~ ✅ **JIT provisioning is on**, and the reasoning is
   in `TokenService._resolve_user` and §3: it grants *identity, never authority* (no
   `role_binding`, no `user_tag`, `password_hash` NULL) and matches on `external_subject`,
   never on email.

**Frontend half — the sign-in screen and session handling. This is what remains.**

> **Before starting, read §3's `M3.4` entry and §4 items 20–23.** Two things there change
> how this must be built: the API is already written and its shapes are in
> `/openapi.json`, and a *concurrent* refresh is treated as theft by design — item 8 below
> is therefore a correctness requirement, not an optimisation.
>
> **`F0` must land first** (`frontend/` is still an empty directory), and **`M3.7`
> `mnemosctl bootstrap` is now a de-facto prerequisite too**: nothing seeds an org, so
> there is no tenant to sign into by hand (§4 item 21). Pull `M3.7` forward or seed a row
> by hand and say which was done.
>
> **What the backend already gives you**, so none of it gets rebuilt in the browser:
> `GET /api/v1/auth/oidc/authorize?org=…` 307s to Keycloak; the callback returns
> `{access_token, token_type, expires_in, org_slug}` and sets the refresh cookie itself;
> `POST /api/v1/auth/token` with body `{"grant_type":"refresh_token"}` and
> `credentials: "include"` rotates; `POST /api/v1/auth/token:revoke` signs out and always
> answers 204. **There is no `refresh_token` field anywhere in the API** — do not add one,
> and do not put a token in `localStorage`.

7. **Sign-in route.** Org slug field, then "Continue with Keycloak" driving
   `GET /api/v1/auth/oidc/authorize?org=…`. Design per DesignSystem §4: one `filled`
   button, real `<form>` semantics, `aria-live` for the error.
   **Every failure renders the same message** — the backend already guarantees one constant
   denial string, and the UI must not undo that by branching on anything to say "no such
   org" (this is exactly the M3.2a mistake, one layer further out).
8. **Session handling.** Access token in memory, refresh in an `httpOnly` cookie set by
   the API — *not* `localStorage`, which is readable by any XSS. A TanStack Query
   interceptor refreshes on 401 once, and on a second 401 clears state and returns to
   sign-in. Concurrent 401s must trigger **one** refresh, not one per in-flight request:
   the rotation chain treats the second use as theft and would kill the family.
9. **The protected shell.** F0's layout behind an auth boundary; unauthenticated visits
   redirect to sign-in preserving the intended destination. Sign-out calls
   `token:revoke`. The signed-in user appears in the sidebar footer.

**Acceptance**

Backend, all ✅ and evidenced in §3:
- ~~`test_rotated_refresh_token_revokes_family`~~ — the M3-level criterion.
- ~~`test_access_token_carries_no_roles_or_permissions`~~ — decoded claims inspected
  directly, without verification, so it asserts the wire bytes and not our own parser.
- ~~`test_a_token_signed_with_another_algorithm_is_rejected`~~, including `alg: none`,
  hand-forged from `base64`/`hmac`.
- ~~`test_expired_access_token_is_rejected`~~, zero leeway, asserted at the boundary second.
- ~~`test_refresh_token_for_one_org_is_useless_against_another`~~.
- ~~A boundary test that the token endpoints leak nothing in the body~~ — and it was
  *verified to fail* by restoring the leak, rather than assumed to work.
- ~~`pytest` green, `ruff` + `mypy --strict` clean, `alembic check` clean, no migration.~~

Frontend, remaining:
- `test_concurrent_401s_trigger_exactly_one_refresh` — the one that prevents a
  self-inflicted family revocation. §4 item 23 explains why this is correctness, not
  polish.
- `test_signin_error_is_identical_for_unknown_org_and_denied_login`.
- **No refresh token in `localStorage` or `sessionStorage`** — grep the built bundle, the
  way `F0`'s `test_no_component_hardcodes_a_colour` greps for hex literals. The API cannot
  hand one out, so this catches a client that invents its own storage.
- A **Playwright** run: sign in against the live Keycloak, land on the shell, reload and
  stay signed in, sign out. Skippable like M3.3's live tests, and **verify it actually
  skips** with the stack down rather than assuming it does. Note that this is also the only
  thing that will exercise Keycloak's *login form*: the backend's live evidence drove
  `authorize` and everything after the callback, but scripting the form itself with `httpx`
  hit Keycloak 26's browser-session requirements and was not worth fighting for — that is
  precisely what a browser driver is for.
- Frontend: `tsc`, ESLint, `axe` clean. **Backend untouched**: `pytest` still 183 passed.

### Then, still in M3 — each with its UI slice, one commit each

- **`M3.5` API keys** — argon2id (same `PasswordHasher`; an API-key secret is low-entropy
  enough to deserve it), `prefix` for identification, plaintext shown once, org folded into
  the id half.
  **UI:** a keys list, a create dialog that shows the secret **exactly once** with a copy
  button and an unmissable "this will not be shown again", and revoke with a confirmation
  that names the key (DesignSystem §4, destructive actions).
- **`M3.6` RBAC dependency** — deny by default, permission as set membership against
  `PermissionSet`. `test_unauthenticated_request_is_denied_by_default` on a route with
  **no** explicit guard is the one that matters: it must fail closed.
  **UI:** the shell hides what the principal cannot reach and renders a real 403 state for
  what it reaches anyway. Hiding a control is a courtesy, never the control itself.
- ~~**`M3.7` `mnemosctl bootstrap`**~~ **✅ done 2026-08-02** — first org, admin user,
  system roles, both `identity_provider` rows and `org.settings.default_provider`. The
  elevation is one statement wide: only the org insert runs in
  `Database.elevated_session()`, and the other nine run under the tenant GUC. Idempotent
  as create-if-absent with no updates. Evidence, the live run and the discharged
  "nothing can be exercised by hand" claim are in §3; the costs are §4 items 20–23.
  **UI: deliberately none, and that is the C12 record.** A CLI is its own interface. This
  command runs *before* anybody can sign in, so an authenticated screen for it would be
  one nobody can reach and an unauthenticated one would be org creation open to the
  internet. Stated here rather than left implied, as C12 requires.

**Acceptance for M3 overall**

- ~~Keycloak login round-trips~~ ✅ to a verified subject (M3.3); to a **platform JWT** is
  `M3.4`.
- ~~`test_cross_org_read_returns_zero_rows`~~ ✅ done in the prerequisite; see §3.
- `test_rotated_refresh_token_revokes_family`.
- `test_unauthenticated_request_is_denied_by_default` on a route with no explicit guard.
- **A person can sign in through the browser and stay signed in.** New, and it is the
  criterion that makes M3 real rather than merely tested.
- `alembic check` still clean; `pytest` green.

**Commit shape:** one commit per numbered deliverable, not one for the milestone. A
backend deliverable and its UI slice may share a commit or be adjacent commits — but not
adjacent *milestones* (C12).

### Then, in order — each milestone is both halves (§3.0, C12)

- **`M4`** — port the `_v1` kernel to asyncpg + pgvector; re-run the benchmark on Postgres
  and update the README numbers. Rolls in old tasks `N2` (cache `all_chunks()`) and
  `N3` (`tiktoken` adapter), cheap once the code has moved.
  **UI: the context inspector** — the signature screen. For a selected message: what was
  admitted, what was excluded and *why* (superseded revision, failed ACL, deduped,
  over budget), token spend against the budget, and the ranked candidates that lost.
  This is the screen that makes the headline numbers legible instead of a README claim,
  so it is worth more design attention than anything else in the app.
- **`M5`** — objectstore (MinIO) + connectors port/factory + Redis Streams events.
  **UI:** connect a source, browse it, watch events arrive live.
- **`M6`** — knowledge: extract, chunk, embed, ingest jobs. The worker's reaper exists;
  give it real jobs to reap.
  **UI:** knowledge library, drag-and-drop upload, per-job progress with the heartbeat and
  stuck-job states surfaced — a job that silently dies is the failure this milestone's
  backend is specifically built to detect, so the UI must show it.
- **`M7`** — LLM gateway (Ollama), versioned prompt store, cost ledger.
  **UI:** prompt manager with version diff and activate; cost dashboard.
- **`M8`** — chat: sessions, messages, SSE, bookmarks, feedback, folders.
  **UI: the chat surface** — the main product screen. Token-by-token streaming (never a
  spinner over a blank region, DesignSystem §4), folders, bookmarks, feedback.
- **`M9`** — RAG flow with citations. **UI:** citations inline, click-through into the M4
  inspector.
- **`M10`** — NL2SQL. **UI:** generated SQL, result grid, narration, and a visible refusal
  when the AST guard rejects a statement.
- **`M11`** — MCP tool runtime. **UI:** tool console and approval dialogs; a call denied by
  trust tier must name the offending source on screen, not only in a log.
- **`M12`** — router. **UI:** which flow handled each message, and why.
- **`M14`** — realtime WS, nginx, e2e, docs. **UI:** live streaming/presence polish and
  Playwright coverage over the whole stack.

`M13` is dissolved; see §3.0. [ADAPTATION §7](docs/ADAPTATION.md#7-milestones) carries the
same table.

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
