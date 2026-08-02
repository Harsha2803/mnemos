# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It states what is built, the constraints
> you must not violate, and the exact next task. When you finish work, update this file
> **and [`docs/ADAPTATION.md`](docs/ADAPTATION.md)** *in the same commit* — a stale
> tracker is worse than none.

**Last updated:** 2026-08-02
**Phase:** M3 — identity. RLS prerequisite + `M3.1` + `M3.2` (+ error-boundary fix) + `M3.3` (OIDC round trip) done; deliverables 4–7 remain
**Next task:** `M3.4`, fully specified in §5. Take them one at a time, in order
**Branch:** `feat/m3-identity` (PR #2, draft). M1+M2 merged to `main` as PR #1

---

## 0. Agent operating instructions

1. **Read in this order:** this file → [`docs/ADAPTATION.md`](docs/ADAPTATION.md) →
   `README.md` → the module you are changing →
   [`docs/CodingStandards.md`](docs/CodingStandards.md).
   This file tells you *what to do next*. ADAPTATION tells you *what the thing is* —
   architecture, the JIVA capability map, the schema plan, and the M1–M14 ledger.
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
8. **One task per session.** Finish whatever the previous session left unfinished; if
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

---

## 3. Current state — what is actually built

Milestone ledger and exit criteria live in [ADAPTATION §7](docs/ADAPTATION.md#7-milestones).
Detailed evidence for each ✅ is in [ADAPTATION §8](docs/ADAPTATION.md#8-current-state).

| Milestone | Status |
|---|---|
| M1 container stack + backend skeleton | ✅ nine services healthy |
| M2 Alembic + full schema | ✅ 41 tables, 4 revisions, `alembic check` clean |
| M3 identity | 🟡 **in progress** — prerequisite + `M3.1` + `M3.2` + `M3.3` done, `M3.4`–`M3.7` remain |
| M4 port memory/retrieval/context kernel to PG | ⬜ |
| M5–M14 | ⬜ |

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
| Tests | `cd backend && ../.venv/bin/python -m pytest` → **97 passed** (needs Docker + Keycloak; see §4.8) |
| Fast tests | everything except `test_tenant_isolation.py` → **92 passed in 2.6s**, no Docker. The 2 live-Keycloak tests skip cleanly when the stack is down |
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
11. **The frontend is an empty directory.** `web` is behind a compose profile so it does
    not break `up`. M13. Until then the only UI is Swagger at `http://localhost:8000/docs`,
    the Keycloak console at `:8080` (`admin`/`admin`) and the MinIO console at `:9001`.
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
    by M3.2, which issues no tokens. **M3.4 must pick one and reconcile both documents** —
    see §5.
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
17. **The OIDC callback returns a subject, not a token.** Deliberate — M3.4 replaces the
    response with an access/refresh pair. Until then there is no way to *stay* logged in,
    only to prove a login happened.

---

## 5. NEXT TASK

### `M3.4` — platform JWT issuance + refresh-token rotation

**Do this one only.** M3.3 is done — see §3. A login now proves who someone is and then
forgets it: the callback returns a subject and there is no way to *stay* logged in. M3.4
mints the platform's own tokens and makes a session survive.

**Why now.** Every route from M3.6 onward is guarded by a `Principal`, and a `Principal`
comes from a platform token. Until this exists there is nothing to guard with, and the
OIDC round trip lands nowhere.

**Read first:** `features/identity/application/oidc_login.py` (what hands you a subject),
`features/identity/adapters/models.py` — the `Session` model, especially `rotated_to`,
`refresh_token_hash` and `uq_session_refresh_token_hash` — `core/security.py`
(`digest_token` already exists for exactly this), `docs/APIContract.md` §2,
`docs/ThreatModel.md` §5, and `entrypoints/api/routers/auth.py`.

**Settle the algorithm conflict first — it is a prerequisite, not a footnote.**
`ThreatModel.md` §5 specifies **EdDSA (Ed25519)**; the committed `core/config.py`
specifies **HS256** with a shared secret. Pick one, and:

- **HS256 is defensible** while api, worker and realtime share one trust domain and one
  secret, and it is what is configured today. The security-critical half is not the
  algorithm but the **allow-list**: never read `alg` from the token.
  `providers/oidc.py` already shows the shape (`ALLOWED_ALGORITHMS`, passed to the
  decoder) — reuse that discipline rather than reinventing it.
- **EdDSA** buys asymmetric verification, so a future service can verify without holding
  a signing key. That is real, and it is also not needed by anything that exists.
- Whichever way it goes: **update `ThreatModel.md` and `core/config.py` so they agree**,
  and record the decision in §4. Do not implement one and leave both documents standing —
  that is the state today and it is why this paragraph exists.

**Scope.**

1. **Access tokens.** 15 minutes (`settings.access_token_ttl_s`). **Identity only — no
   roles, no permissions, no tags in the claims.** `APIContract.md` §2 is explicit and the
   reason is worth restating: a token carrying `roles` keeps working after the role is
   revoked, and that window is exactly what an attacker looks for. Roles resolve per
   request from the database (M3.6). Claims: `sub` (the `app_user.id`), `org` (the org
   id), `sid` (the session id), `iat`, `exp`, `iss`, `jti`. Verification must pin the
   algorithm, `iss`, and expiry with no leeway.
2. **Refresh tokens.** High-entropy random from `secrets`, stored **SHA-256-hashed** via
   the existing `core.security.digest_token` — *not* argon2id, and the docstring there
   already carries the reason a reviewer will ask for (`uq_session_refresh_token_hash` is
   a unique index, and argon2's per-row salt would make the column unsearchable; the input
   has no dictionary to slow down). Compare with `tokens_equal`.
3. **Rotation, and the family kill.** Every use of a refresh token issues a new one and
   sets the old row's `rotated_to` to the new row's id. Presenting a token whose row
   already has `rotated_to` set **proves theft** — the legitimate holder and the thief
   cannot both have the current token — so revoke **the entire chain**, not just that row.
   Walk `rotated_to` to the head and revoke forward, and set `revoked_reason`.
4. **The org travels in the credential.** Settled in M3.2 and it applies here: the refresh
   token must name its tenant, because `session` is org-scoped and unreadable until the
   org is known. Format it as `<org_slug>.<secret>`, and note that `APIContract.md` §1
   specifies `X-API-Key: <key_id>.<secret>` — the same refinement lands there in M3.5.
   **`APIContract.md` must be updated in this commit** either way.
5. **Wire it into the OIDC callback**, replacing `SubjectResponse` with the token pair
   from `APIContract.md` §2. The subject must be mapped to a local `app_user` — this is
   where just-in-time provisioning from an external IdP is decided. If you provision,
   `app_user.provider_id` and `external_subject` are the columns, and `password_hash`
   stays `NULL` (M3.2 already refuses to password-authenticate such a user).
6. **`POST /v1/auth/token` with `grant_type=refresh_token`**, and
   `POST /v1/auth/token:revoke`.

**Acceptance**
- `test_rotated_refresh_token_revokes_family` — **the M3-level criterion.** Use a token,
  use the *old* one again, assert the whole chain is revoked and that the newest token
  stops working too.
- `test_access_token_carries_no_roles_or_permissions` — inspect the claims directly.
- `test_a_token_signed_with_another_algorithm_is_rejected` — including `alg: none` and,
  if you land HS256, an asymmetric-signed token. Mirror
  `test_oidc_provider_rejects_an_unsigned_token`, which hand-forges rather than relying on
  PyJWT to mint the forgery.
- `test_expired_access_token_is_rejected` with zero leeway.
- `test_refresh_token_for_one_org_is_useless_against_another`.
- A live-stack test end-to-end: real Keycloak token → platform token pair → refresh →
  rotation. Mark it skippable like M3.3's, and **verify it actually skips** with the stack
  down rather than assuming it does.
- `pytest` green, `ruff` + `mypy --strict` clean on new files, `alembic check` clean —
  M3.4 should need **no migration**; `session` already has every column.

### Then, still in M3, one commit each

5. API-key auth: argon2id hash (`core/security.PasswordHasher` — the same hasher; an
   API-key secret is low-entropy enough to deserve it), `prefix` for identification,
   plaintext shown once, org folded into the id half per M3.2's decision.
6. RBAC dependency for FastAPI: deny by default, permission checked as set membership
   against `PermissionSet` from M3.1. `test_unauthenticated_request_is_denied_by_default`
   on a route with **no** explicit guard is the one that matters — it must fail closed.
7. `mnemosctl bootstrap` — create the first org, admin user and system roles through
   `Database.elevated_session()` (`SET LOCAL ROLE mnemos_admin`), because the very first
   insert has no org to scope to. Also seed `org.settings.default_provider`, which is what
   `ProviderFactory` reads when a login names no provider, and seed the org's
   `identity_provider` rows — without them nothing in M3.2/M3.3 can be exercised by hand.

**Acceptance for M3 overall**

- ~~Keycloak login round-trips~~ ✅ to a verified subject (M3.3); to a **platform JWT** is
  M3.4.
- ~~`test_cross_org_read_returns_zero_rows`~~ ✅ done in the prerequisite; see §3.
- `test_rotated_refresh_token_revokes_family`.
- `test_unauthenticated_request_is_denied_by_default` on a route with no explicit guard.
- `alembic check` still clean; `pytest` green.

**Commit shape:** one commit per numbered deliverable, not one for the milestone.

### Then, in order

- `M4` — port the `_v1` kernel to asyncpg + pgvector; re-run the benchmark on Postgres
  and update the README numbers. Rolls in old tasks `N2` (cache `all_chunks()`) and
  `N3` (`tiktoken` adapter), which are cheap once the code has moved.
- `M5` — objectstore (MinIO) + connectors port/factory + Redis Streams events.
- `M6` — knowledge: extract, chunk, embed, ingest jobs. The worker's reaper already
  exists; give it real jobs to reap.
- `M7`–`M14` — see [ADAPTATION §7](docs/ADAPTATION.md#7-milestones).

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
7. Push the branch and make sure its PR exists.
