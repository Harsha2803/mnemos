# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It states what is built, the constraints
> you must not violate, and the exact next task. When you finish work, update this file
> **and [`docs/ADAPTATION.md`](docs/ADAPTATION.md)** *in the same commit* — a stale
> tracker is worse than none.

**Last updated:** 2026-07-27
**Phase:** M3 — identity. The RLS prerequisite is done; deliverables 1–7 remain
**Next task:** `M3.1`, fully specified in §5. Take them one at a time, in order
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
| M3 identity | 🟡 **in progress** — prerequisite done, `M3.1`–`M3.7` remain |
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
| Tests | `cd backend && ../.venv/bin/python -m pytest -q` → 28 passed (needs Docker; see §4.8) |
| Fast tests | `cd backend && ../.venv/bin/python -m pytest -q tests/test_invariants.py` → 23, hermetic |
| DB roles | `migrate` connects as `mnemos` (owner). api/worker/realtime connect as `mnemos_app` |
| Host ports | postgres `15432`, redis `6380`, api `8000`, realtime `8001`, keycloak `8080`, minio `9000/9001`, ollama `11434` |
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
    not break `up`. M13.

---

## 5. NEXT TASK

### `M3.1` — `features/identity/domain/`: `Principal`, `Permission`, `TagSet`

**Do this one only.** The remaining M3 deliverables are specified below so the shape is
visible, but they are separate tasks with separate commits. Nothing about M3.1 depends on
having read ahead.

**Why M3 at all.** Every subsequent milestone needs a caller with an org and a tag set.
Retrieval cannot push authorization into the scan without a real principal, so building
M4–M12 first would mean building them against a fake one and rewiring later.

**Read first:** ADAPTATION §3 (the `auth_modules/providers` → `features/identity` row),
§5 (layering), `docs/CodingStandards.md` §2, and `docs/ThreatModel.md`.

**Scope.** Pure types only. **No SQLAlchemy import anywhere in `domain/`** — that is the
layering rule, and it is what lets these be unit-tested in microseconds. No repository, no
provider, no FastAPI. `features/identity/adapters/models.py` already exists and stays
untouched.

- `Principal` — who is calling: `org_id`, `principal_id`, kind (`user` vs `service`,
  because an API key is not a person), granted permissions, tag set, and the
  `session_id` / `api_key_id` that authenticated it. Frozen; a mutable principal is a
  privilege-escalation primitive.
- `Permission` — `resource:action`, which is the string form already stored in
  `role.permissions` JSONB. Parse tolerantly (an unknown permission in a role is
  harmless — nothing requires it), but expose typed constructors so a route guard cannot
  typo a permission into permanent denial.
- `TagSet` — a set of tag slugs with an `overlaps()` test. **This is why the retrieval
  scan can push authorization into the `WHERE` clause** (C4): tag authorization is a
  set-overlap, and set-overlap is expressible in SQL. Keep it that way.
- Identifier `NewType`s (`OrgId`, `UserId`, `RoleId`, `TagId`, `SessionId`, `ApiKeyId`,
  `ProviderId`). Every id here is a UUID, so without newtypes `revoke(user_id, org_id)`
  type-checks with the arguments swapped, and in a multi-tenant system that is a leak.

**Acceptance**
- `test_permission_denies_by_default` — a permission absent from the set is refused.
- `test_wildcard_grant_allows_specific_permission` — `*:*` and `memory:*` both work.
- `test_wildcard_in_a_requirement_is_rejected` — requiring `memory:*` is a bug, not a
  broad check, and must raise rather than silently over-grant.
- `test_tag_overlap_is_symmetric_and_empty_set_grants_nothing`.
- Import-time proof that `domain/` pulls in no SQLAlchemy.
- `pytest` green, `ruff check` clean on the new files.

### Then, still in M3, one commit each

2. `features/identity/providers/` — `AuthProvider` protocol + `InternalProvider`
   (argon2id) and `OidcProvider` (Keycloak), selected by a factory reading the
   `identity_provider` table. **Strategy + Factory + composition root**, mirroring the
   shape in ADAPTATION §3 — two protocols, not four.
3. Split-horizon OIDC honoured: validate `iss` against `issuer_internal`, redirect the
   browser to `issuer_public`. JWKS fetched over the internal URL and cached for
   `oidc_jwks_cache_s`. **The Keycloak realm currently allows only
   `http://localhost:3000/*` as a redirect URI** (`deploy/keycloak/mnemos-realm.json`);
   a backend-driven code+PKCE flow needs the API callback added. Keycloak runs
   `start-dev` with no volume, so `docker compose up -d --force-recreate keycloak`
   re-imports the realm.
4. Platform JWT issuance + refresh-token rotation using the `session` table's
   `rotated_to` chain. Presenting an already-rotated token revokes the whole family.
5. API-key auth: argon2id hash, `prefix` for identification, plaintext shown once.
6. RBAC dependency for FastAPI: deny by default, permission checked as set membership.
7. `mnemosctl bootstrap` — create the first org, admin user and system roles. Run it
   through `Database.elevated_session()` (added by the M3 prerequisite), which is
   `SET LOCAL ROLE mnemos_admin`, because the very first insert has no org to scope to.

**Two design questions M3.2–M3.5 must answer, surfaced by the RLS work and not yet
settled.** Neither is a licence to re-litigate §2 — both are new consequences of RLS
actually being in force:

- **Credentials must carry their tenant.** `app_user`, `session`, `api_key` and
  `identity_provider` are all org-scoped, and `org` is the only table without RLS. So
  nothing about a caller is readable until an org is known, and a bare
  `Authorization: Bearer` or `X-API-Key` no longer identifies anybody. Either every
  credential encodes its org (password grant takes an org slug; refresh token and API key
  become `<org>.<secret>` / `<org>_<prefix>.<secret>`), or `BYPASSRLS` enters the
  authenticated request path. **Recommendation: carry the tenant in the credential** — it
  keeps `elevated_session()` down to its single bootstrap call site. Note that
  `APIContract.md` §1 currently specifies `X-API-Key: <key_id>.<secret>`; folding the org
  into the id half is a refinement of that, and APIContract must be updated in the same
  commit either way.
- **Refresh tokens hash with SHA-256, not argon2id.** `uq_session_refresh_token_hash` is
  a unique index, and argon2's per-row salt makes a hash column unsearchable. That is
  correct rather than a compromise: refresh tokens are high-entropy random strings, so
  there is no dictionary to slow down. Argon2id stays on passwords and API-key secrets,
  which is where the entropy is low. Say so in a docstring, because "why isn't this
  argon2 too" is the first question a reviewer will ask.
- **`ThreatModel.md` §"Cryptography" specifies EdDSA (Ed25519) for tokens; the committed
  `core/config.py` specifies HS256** with a shared secret. This is a real conflict in the
  docs, not a gap in the code, and M3.4 has to pick one. HS256 with a strict algorithm
  allow-list (never read `alg` from the token — that control is the security-critical
  half) is defensible while API, worker and realtime share one trust domain and one
  secret. Whichever way it goes, **record it in §4 and reconcile the two documents.** Do
  not implement one and leave both documents standing.

**Acceptance for M3 overall**

- Keycloak login round-trips to a platform JWT.
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
