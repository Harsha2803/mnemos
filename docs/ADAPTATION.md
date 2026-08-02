# Mnemos — Build Plan & JIVA Adaptation Map

> **Read this first if you are resuming work.** It is the authoritative plan and is
> self-contained: architecture, capability map, schema, milestones, and current state.
> [`TRACKER.md`](../TRACKER.md) holds live task status; this holds the design.

**Last updated:** 2026-08-02

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

| ID | Backend half | Frontend half (same milestone — see TRACKER §3.0) |
|---|---|---|
| **M1** | Container stack + backend skeleton | — |
| **M2** | Alembic + full schema | — |
| **F0** | — | App shell: Next.js, design tokens, three-column layout, theming, primitives, generated client |
| **M3** | Identity: internal auth, JWT, RBAC, tags, OIDC, API keys | Sign-in, session handling, protected shell, API-key management |
| **M4** | Port memory/retrieval/context kernel to PG + pgvector | **Context inspector** — admitted vs excluded and why, budget spend, losing candidates |
| **M5** | objectstore (MinIO) + connectors + Redis Streams events | Sources: connect, browse, watch events |
| **M6** | Knowledge: extract, chunk, embed, jobs w/ heartbeat | Knowledge library, upload, live job progress incl. stuck-job state |
| **M7** | LLM gateway (Ollama) + versioned prompts + cost ledger | Prompt manager (version diff, activate) + cost dashboard |
| **M8** | Chat: sessions, messages, SSE, bookmarks, feedback, folders | **The chat surface** — token streaming, folders, bookmarks |
| **M9** | RAG flow + citations | Citations inline, click-through into the M4 inspector |
| **M10** | NL2SQL: introspection, AST guard, read-only role, narration | SQL panel: generated SQL, result grid, narration, visible guard refusals |
| **M11** | MCP tool runtime: registry, calling, creds, approval gates | Tool console + approval dialogs; denials name the offending source on screen |
| **M12** | Router: classify → RAG / NL2SQL / tools / memory / chat | Flow indicator per message, and why it was chosen |
| **M13** | ~~Next.js frontend~~ — **dissolved** into F0 + the slices above | — |
| **M14** | Realtime WS, nginx, e2e verification, docs | Live streaming/presence polish; Playwright over the whole stack |

**Exit criterion for every milestone from F0 onward: both halves land.** A milestone with
an untouched `frontend/` is not complete (TRACKER C12). `M13` used to be "build every
screen at the end"; that guaranteed the APIs would be shaped without a consumer and that
the whole UI would land as one unreviewable drop, so it was dissolved on 2026-08-02.

The UI follows [`DesignSystem.md`](DesignSystem.md), which is normative. It is Mnemos's
own system — its own accent, neutrals and identity — informed by Apple's design resources
for typography, spatial rhythm, materials and motion character. §0 there records which
Apple assets are off-limits (SF Pro as a webfont, SF Symbols) and what is used instead.

**Current position: M1, M2 and `M3.1`–`M3.3` are merged to `main` (PR #1, PR #2 at
`98fe47a`). `M3.4`'s **backend half** is on `feat/m3.4-platform-jwt` (PR #6); its UI slice
is not built. `F0`, the frontend foundation, is the task that unblocks every remaining UI
slice — see [TRACKER §5](../TRACKER.md#5-next-task). `M3.5`–`M3.7` follow. See §8.**

M3's exit criterion "RLS blocks cross-org" turned out to be unmet by M2 rather than merely
untested; that is written up in §8 and in [TRACKER §3](../TRACKER.md#3-current-state--what-is-actually-built).

---

## 8. Current state

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
trust domain, e.g. a separately-deployed MCP tool service at M11. The part that actually
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
`user_tag`, so the user can sign in and do nothing until M3.6 grants something. Matching is
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

**Remaining in M3: the `M3.4` UI slice, then deliverables 5–7** — the sign-in screen and
session handling, API keys, the RBAC dependency, and `mnemosctl bootstrap`. Specified in
[TRACKER §5](../TRACKER.md#5-next-task). Note that M3.4 landed **without its UI slice**,
which is a C12 exception recorded in [TRACKER §4](../TRACKER.md#4-known-gaps-and-honest-weaknesses)
item 20 rather than glossed over: `frontend/` is still an empty directory, so `F0` has to
exist before a sign-in screen can be built in anything.
**Done: M3.7 — `mnemosctl bootstrap` (2026-08-02).** M3.2 and M3.3 built a provider seam
and an OIDC round trip that nothing could reach: `ProviderFactory` reads
`identity_provider` to choose a strategy, and that table was empty on every database in
existence. `bootstrap` creates the first `org`, the three system roles, **both**
`identity_provider` rows, the admin `app_user` with an argon2id hash, the admin
`role_binding`, and `org.settings.default_provider`.

| File | What it is |
|---|---|
| `domain/roles.py` | `SYSTEM_ROLES` — `admin` (`*:*`), `analyst`, `user`. In `domain/` because M3.6's guard must require against the roles this seeds. Resources are §5's feature packages so a permission traces to the code that enforces it; slugs are the realm's roles minus the `mnemos-` prefix, since a `role` row is already scoped by `org_id` and a Keycloak realm role is not |
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

**Remaining: deliverables 4–6** — JWT issuance and refresh rotation, API keys, and the
RBAC dependency. Specified in [TRACKER §5](../TRACKER.md#5-next-task) (next up: **F0**,
then **M3.4**). One design question is still open and M3.4 must settle it:
**`ThreatModel.md` §5 and `core/config.py` disagree on the token algorithm** (EdDSA vs
HS256). Whichever is chosen, both documents must be reconciled in the same commit.

### Carried over from v0.1 (needs porting from SQLite → Postgres)

`core.py`, `embed.py`, `store.py`, `retrieval.py`, `compiler.py`, `baseline.py`,
`ingest.py`, `dataset.py`, `bench.py`, `app.py`, `cli.py` — quarantined in
`backend/src/mnemos/_v1/`. **The kernel logic is sound and tested (23 tests); it needs
re-homing into the feature layout and re-targeting at asyncpg + pgvector.**

The v0.1 benchmark (naive prompt vs compiled bundle) should be **kept** — it is the
evidence for the memory/context differentiator. Re-point it at Postgres.

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

**`web` is behind a compose profile.** `./frontend` has no Dockerfile until M13, and an
unresolvable build context aborted the whole `up`. Default `up` brings up the working
stack; `docker compose --profile web up` opts in once M13 lands.

### Not started

M3 deliverables 2–7, then M4 onward. The identity feature — internal auth, JWT, RBAC,
tags, OIDC via Strategy/Factory, API keys — is in progress: its RLS prerequisite and the
pure domain types (`M3.1`) are done, and the next unit of work is `M3.2`, the provider
Strategy/Factory. Keycloak is running with the
realm imported, so the OIDC half has a real provider to talk to on day one — though the
imported realm currently permits only `http://localhost:3000/*` as a redirect URI, so a
backend-driven code+PKCE flow needs the API callback added to
`deploy/keycloak/mnemos-realm.json` first.

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
- The v0.1 benchmark numbers in the root `README.md` were measured on SQLite. After the
  Postgres port, **re-run and update them** — do not let published numbers drift.
- `docs/` (Architecture, SystemDesign, DatabaseDesign, APIContract, ThreatModel, 12 ADRs)
  describes a larger target than what is built. That gap is stated in the README and is
  intentional; keep it stated.
- Known weakness carried from v0.1: brute-force cosine over all chunks per query. Fine at
  demo scale, must become a pgvector HNSW index query in M4.
- Do not re-run `pkill -f mnemos` — it matches the agent's own shell. Kill by port/PID.
