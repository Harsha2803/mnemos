# API Contract

**Base URL:** `/v1` · **Media type:** `application/json` · **Spec:** OpenAPI 3.1,
generated from Pydantic v2 models — the code is the source of truth, this document is
the rationale.

---

## 1. Design rules

| Rule | Detail |
|---|---|
| Versioning | Path-versioned (`/v1`). Breaking changes ship as `/v2`; additive changes never bump. |
| Naming | Plural nouns for collections. Non-CRUD actions use a colon suffix: `POST /v1/context:compile`. Verbs-as-paths (`/compileContext`) are not used. |
| Identifiers | UUIDv7 everywhere, opaque to clients. Never expose sequential integers. |
| Time | RFC 3339 with explicit offset, always UTC (`2026-07-26T09:15:00Z`). |
| Idempotency | Every unsafe method accepts `Idempotency-Key`. Required on `POST /v1/memories` and all tool invocations. |
| Partial responses | `?fields=` projection on read endpoints returning large payloads. |
| Errors | RFC 9457 Problem Details. One shape, always. |
| Auth | `Authorization: Bearer <jwt>` or `X-API-Key: <org_slug>.<secret>`. The refresh token travels as an `httpOnly` cookie, never in a body. |
| Tenancy | Derived from the credential. **Never** from a header or query parameter. |

**Why the credential's first half is the org slug and not a key id** (settled in M3.2,
implemented in M3.4). Every table an authenticated caller touches is under row-level
security, so *nothing about them is readable until an org is known* — a bare secret, or a
bare key id, identifies nobody. Looking one up across all tenants first would mean
`BYPASSRLS` in the request path, which is exactly the exemption the M3 prerequisite
removed. Naming the tenant in the credential costs nothing and keeps the authentication
path unprivileged. The slug is hashed *together with* the secret, so it is a binding and
not a hint: the same secret presented under another tenant's slug digests to something no
row holds.

**Why the colon-action convention.** Context compilation is not a resource creation in
any honest REST sense — it is a computation with a cached, content-addressed result.
Modelling it as `POST /v1/contexts` implies a collection whose members can be listed and
mutated, which is wrong. The `:compile` form (an established Google AIP convention) says
plainly that this is an operation, while keeping the resource namespace meaningful.

## 2. Authentication

Routes are served under the configured `api_prefix`, which is `/api/v1` — so the paths
below are `/api/v1/auth/…` in a running system.

```http
POST /v1/auth/token
Content-Type: application/json
Cookie: mnemos_refresh=<org_slug>.<secret>

{ "grant_type": "refresh_token" }
```

```json
{
  "access_token": "eyJhbGciOi…",
  "token_type": "Bearer",
  "expires_in": 900,
  "org_slug": "acme"
}
```

| Endpoint | Purpose | Status |
|---|---|---|
| `GET /v1/auth/oidc/authorize` | Begin OIDC authorization code + PKCE | ✅ M3.3 |
| `GET /v1/auth/oidc/callback` | OIDC callback → token pair, refresh cookie set | ✅ M3.4 |
| `POST /v1/auth/token` | `grant_type=refresh_token`; rotates | ✅ M3.4 |
| `POST /v1/auth/token:revoke` | Revoke a refresh token and its whole chain | ✅ M3.4 |
| `POST /v1/auth/token` (`password`, `api_key`) | The other two grants | M3.5 |
| `GET /v1/auth/providers` | Enabled identity providers for a given email domain | M3.5 |
| `GET /v1/auth/me` | Current principal, effective roles, scopes | M3.6 |

**Access tokens are 15 minutes and carry no authorization decisions** — only identity.
The claims are exactly `sub`, `org`, `sid`, `iat`, `exp`, `iss`, `jti`, and the codec
refuses a token carrying `roles`, `scope`, `permissions` or their relatives in *both*
directions — minting and verifying. Roles and grants are resolved from the database on
every request. A token that carries a `roles` claim is a token that keeps working after
the role is revoked, which is a window an attacker will find. The cost is a cached lookup;
the benefit is that revocation is immediate.

There is no `scope` field in the response, for the same reason: there is no authorization
in the token to report. `GET /v1/auth/me` (M3.6) answers that against the live database.

**The refresh token is never in a response body.** It is set as an `httpOnly`,
`SameSite=Lax`, `Path=/api/v1/auth` cookie, `Secure` outside local development. A body is
the part of a response most likely to reach a log, a proxy cache or a pasted bug report,
and a browser client handed a refresh token in JSON keeps it where any XSS can read it.
`SameSite=Lax` plus POST-only endpoints is what makes a cookie-borne credential safe to
accept: Lax withholds it from cross-site POSTs, so a forged cross-origin form sends
nothing. A non-browser client may send `refresh_token` in the request body instead; both
endpoints read the body first and fall back to the cookie.

**Every use of a refresh token rotates it, and reuse kills the family.** The old row
records its successor in `session.rotated_to`; presenting a token whose row already names
one is proof of theft — the legitimate holder and the thief cannot both hold the current
token — so the entire chain is revoked with `revoked_reason`, and both parties log in
again. *Concurrent* refreshes are indistinguishable from theft and must be collapsed by
the client into one in-flight call.

`POST /v1/auth/token:revoke` **always answers 204**, whatever was presented (RFC 7009
§2.2). Answering 401 for an unknown token and 204 for a known one is a free oracle for
testing stolen credentials, from a caller whose only authentication *is* the token.

Every failure at these endpoints returns the same body —
`{"error":{"code":"unauthenticated","message":"authentication failed"}}` — for an unknown
org, an unknown token, a malformed credential and a revoked family alike. The diagnostic
reason goes to the log. A client must not branch on it to say anything more specific.

API keys are `<org_slug>.<secret>` (M3.5); the secret half is argon2id-hashed, because an
API-key secret is low-entropy enough to deserve it. Refresh tokens are 256 bits from
`secrets` and are SHA-256 digested instead — there is no dictionary for a work factor to
slow down, and the digest column has to stay searchable by a unique index.

## 3. Memory

### Write a claim

```http
POST /v1/memories
Idempotency-Key: 018f3c1e-…

{
  "kind": "semantic",
  "subject": { "type": "user", "id": "018f…" },
  "predicate": "prefers_language",
  "object": "Python",
  "valid_from": "2026-07-01T00:00:00Z",
  "valid_to": null,
  "confidence": 0.92,
  "source": { "kind": "agent", "ref": "run_018f…" },
  "scope": { "workspace_id": "018f…", "sensitivity": "internal", "tags": ["prefs"] }
}
```

`201 Created`:

```json
{
  "id": "018f…",
  "kind": "semantic",
  "valid_from": "2026-07-01T00:00:00Z",
  "valid_to": null,
  "recorded_at": "2026-07-26T09:15:00Z",
  "retracted_at": null,
  "trust_tier": 2,
  "importance": 0.61,
  "strength": 1.0,
  "arbitration": {
    "superseded": [
      { "id": "018e…", "predicate": "prefers_language",
        "object": "Java", "reason": "later_valid_from" }
    ],
    "contradicted": [],
    "outcome": "asserted"
  },
  "indexing": { "status": "pending", "eta_seconds": 3 }
}
```

Two parts of this response are deliberate and unusual:

**`arbitration`** tells the caller what their write *did to existing beliefs*. A memory
API that silently supersedes prior claims is one whose behaviour can only be discovered
by reading the database. Returning the supersession makes the bitemporal model visible
at the API boundary, which is where it needs to be understood.

**`indexing.status`** states the consistency guarantee inline. The claim is durable and
readable immediately; it becomes semantically searchable within seconds because
embedding is an out-of-band call. Documenting this as a field rather than a footnote
prevents the class of bug where a caller writes then immediately searches and concludes
the system is broken.

### Query memory

```http
GET /v1/memories?subject_id=018f…&kind=semantic&as_of=2026-03-01T00:00:00Z
                &believed_at=2026-03-15T00:00:00Z&limit=50&cursor=…
```

| Parameter | Meaning |
|---|---|
| `as_of` | **World time.** Claims whose `valid_range` contains this instant. |
| `believed_at` | **Belief time.** The system's state of knowledge at this instant. |
| `include_retracted` | Include claims no longer believed (default `false`) |
| `include_tombstoned` | Include compacted claims (default `false`) |

The two independent time axes are the whole point. `as_of=2026-03-01` with
`believed_at=now` answers *"what do we now think was true in March?"*
`as_of=2026-03-01` with `believed_at=2026-03-01` answers *"what did we think in March
was true in March?"* — which is the question an audit actually asks.

### Other memory endpoints

| Endpoint | Purpose |
|---|---|
| `GET /v1/memories/{id}` | Single claim with lineage edges |
| `GET /v1/memories/{id}/lineage` | Supersession/derivation graph, depth-bounded |
| `POST /v1/memories/{id}:retract` | Close belief time. Does **not** delete. |
| `POST /v1/memories:search` | Hybrid semantic + lexical search |
| `POST /v1/memories:consolidate` | Trigger consolidation for a subject (async) |
| `DELETE /v1/memories/{id}?mode=erase` | **Hard delete.** DSR path only — see §9 |

`POST /v1/memories/{id}:retract` and `DELETE …?mode=erase` are separate operations with
separate permissions because they are separate concepts. Retraction says "we no longer
believe this" and is fully auditable. Erasure destroys the record and is irreversible.
An API that conflates them will eventually destroy data someone needed.

## 4. Context — the core surface

### Compile

```http
POST /v1/context:compile

{
  "session_id": "018f…",
  "agent_role": "support_assistant",
  "task": { "type": "answer_question", "query": "What did we decide about the EU rollout?" },
  "budgets": { "tokens": 8000, "latency_ms": 1500, "compute_units": 5.0 },
  "sections": {
    "conversation": { "floor_tokens": 500,  "ceil_tokens": 2000 },
    "memory":       { "floor_tokens": 0,    "ceil_tokens": 3000 },
    "documents":    { "floor_tokens": 0,    "ceil_tokens": 4000 }
  },
  "pins": [ { "kind": "memory", "id": "018f…" } ],
  "explain": true
}
```

`200 OK`:

```json
{
  "digest": "sha256:9f2c7a…",
  "sections": [
    { "name": "policy",       "tokens": 180,  "trust_tier": 0, "content": "…" },
    { "name": "conversation", "tokens": 1240, "trust_tier": 2, "content": "…" },
    { "name": "memory",       "tokens": 2100, "trust_tier": 3, "content": "…" },
    { "name": "documents",    "tokens": 3400, "trust_tier": 5, "content": "…" }
  ],
  "manifest": [
    {
      "section": "memory", "ordinal": 0,
      "source": { "kind": "memory", "id": "018f…", "version": 3 },
      "operator_id": "memory_scan_1",
      "score": 0.87, "rank_before_rerank": 4,
      "tokens": 96, "trust_tier": 3,
      "acl_rule_id": "018f…",
      "compression": null
    }
  ],
  "budget_report": {
    "tokens":        { "requested": 8000, "consumed": 6920, "headroom": 1080 },
    "latency_ms":    { "budget": 1500, "consumed": 412 },
    "compute_units": { "budget": 5.0, "consumed": 0.31 },
    "evicted": [
      { "source": { "kind": "chunk", "id": "018f…" },
        "score": 0.71, "tokens": 620,
        "reason": "section_ceiling_reached", "section": "documents" }
    ]
  },
  "degradations": [
    { "operator_id": "graph_expand_1", "reason": "deadline_exceeded",
      "deadline_ms": 120, "elapsed_ms": 121, "fallback": "skip",
      "impact": "graph_context omitted (est. 640 tokens)" }
  ],
  "explain_ref": "/v1/context/bundles/sha256:9f2c7a…/explain"
}
```

`202 Accepted` is returned instead when the planner's estimated p95 exceeds the
requested `latency_ms`; the body carries a `bundle_job_id` and a WebSocket topic. The
decision is the *planner's*, based on the statistics catalog — not a fixed rule — so
the same request can be inline on a GPU tier and async on CPU.

### `EXPLAIN`

```http
GET /v1/context/bundles/{digest}/explain
```

```json
{
  "digest": "sha256:9f2c7a…",
  "plan_hash": "sha256:1b4e…",
  "catalog_version": 412, "policy_version": 17,
  "logical_plan": {
    "root": "assemble_1",
    "nodes": [
      { "id": "vector_search_1", "op": "VectorSearch",
        "args": { "space": "default", "k": 40 },
        "rewrites_applied": ["R1_acl_pushdown", "R2_projection_pruning"] }
    ]
  },
  "physical_plan": {
    "nodes": [
      { "id": "vector_search_1", "k": 40, "deadline_ms": 80,
        "fallback": "lexical_only",
        "estimated": { "latency_p95_ms": 40, "candidates": 40,
                       "compute_units": 0.02, "utility": 0.61 } }
    ]
  },
  "operator_actuals": [
    { "id": "vector_search_1", "latency_ms": 31, "candidates_in": null,
      "candidates_out": 40, "compute_units": 0.021, "outcome": "ok" },
    { "id": "graph_expand_1", "latency_ms": 121, "candidates_out": 0,
      "outcome": "deadline_exceeded" }
  ],
  "allocator_trace": {
    "strategy": "lagrangian_greedy_density",
    "admitted": 34, "evicted": 11,
    "binding_constraint": "latency_ms",
    "decisions": [
      { "candidate": "chunk:018f…", "utility": 0.71, "tokens": 620,
        "density": 0.00114, "admitted": false,
        "reason": "section_ceiling_reached" }
    ]
  },
  "gates": {
    "rerank": { "fired": true,  "reason": "score_margin_below_threshold",
                "margin": 0.03, "threshold": 0.05 },
    "abstractive_compression": { "fired": false,
                "reason": "compute_cost_exceeds_marginal_utility",
                "est_latency_ms": 6100 }
  }
}
```

`binding_constraint` names which resource the allocator actually ran out of. Under local
CPU inference it will usually be `latency_ms`; on hosted inference, `tokens`. That one
field turns "the answer was bad" into "you were latency-bound, raise the budget or
switch tiers."

### Other context endpoints

| Endpoint | Purpose |
|---|---|
| `GET /v1/context/bundles/{digest}` | Retrieve a bundle by digest (immutable, cacheable forever) |
| `POST /v1/context/bundles/{digest}:replay` | Recompile deterministically; returns a diff if the result differs |
| `POST /v1/context:estimate` | Plan and cost **without executing** — a dry run |
| `POST /v1/context/bundles/{digest}/feedback` | Downstream outcome signal, feeds `utility_prior` |

`POST /v1/context:estimate` exists because the alternative — discovering that a request
would cost 19 seconds by waiting 19 seconds — is not acceptable during development.

## 5. Flow A — RAG over documents

| Endpoint | Purpose |
|---|---|
| `POST /v1/documents:upload-url` | Presigned MinIO upload URL carrying metadata |
| `POST /v1/documents` | Register an uploaded object; enqueues ingestion |
| `GET /v1/documents/{id}` | Metadata + ingestion status + error detail |
| `GET /v1/documents/{id}/chunks` | Chunks with `char_start`/`char_end` for highlighting |
| `POST /v1/documents/{id}:reingest` | Re-run ingestion (new chunker or embedding model) |
| `POST /v1/rag:answer` | Compile context → generate → return answer with citations |

`POST /v1/rag:answer` returns `bundle_digest` alongside the answer, and every citation
carries `document_id`, `page`, and character offsets. An answer without a traceable
citation range is an assertion, not a grounded response.

## 6. Flow B — NL2SQL

| Endpoint | Purpose |
|---|---|
| `POST /v1/sql/datasources` | Register a datasource; DSN encrypted at rest |
| `POST /v1/sql/datasources:test` | Validate connectivity with **inline** credentials, pre-save |
| `POST /v1/sql/datasources/{id}:introspect` | Introspect schema → write schema claims into memory |
| `POST /v1/sql:ask` | NL question → context → SQL → validated execution → narration |
| `GET /v1/sql/runs/{id}` | Full run record including per-attempt safety verdicts |
| `POST /v1/sql/runs/{id}:confirm` | Human approval gate for a high-impact plan |

```json
// POST /v1/sql:ask  → 200
{
  "run_id": "018f…",
  "bundle_digest": "sha256:…",
  "sql": "SELECT region, SUM(revenue) FROM sales WHERE year = 2026 GROUP BY region",
  "safety": {
    "readonly_verdict": "pass",
    "ast_check": "single_readonly_select",
    "authorized_tables": ["sales"],
    "denied_tables": ["payroll"],
    "attempts": [ { "attempt": 1, "readonly_verdict": "pass" } ]
  },
  "result": { "row_count": 4, "columns": ["region", "sum"], "rows": [] },
  "narration": "Revenue in 2026 concentrated in EMEA…",
  "truncated": false
}
```

`denied_tables` is returned rather than hidden. If the model tried to query `payroll`
and authorization pruned it, the caller — and the narration step — must know, so the
answer can say "excluding data you don't have access to" instead of silently reporting
an incomplete figure as complete.

`POST /v1/sql/datasources:test` accepting inline credentials before persistence is a
small thing that matters a lot operationally: it means an admin never saves a broken
connection and then debugs it through a create/update cycle.

## 7. Flow C — Agents and MCP tools

### Agents

| Endpoint | Purpose |
|---|---|
| `POST /v1/agents/runs` | Start a run with explicit budgets |
| `GET /v1/agents/runs/{id}` | State, consumed budget, result |
| `GET /v1/agents/runs/{id}/checkpoints` | Full step timeline with bundle digests |
| `POST /v1/agents/runs/{id}:approve` | Resume from `AWAITING_APPROVAL` |
| `POST /v1/agents/runs/{id}:cancel` | Cooperative cancellation via pub/sub |
| `POST /v1/agents/runs/{id}/checkpoints/{seq}:replay` | Re-execute one step against its exact original context |

### MCP (separate service, `mnemos-tools`)

| Endpoint | Purpose |
|---|---|
| `POST /v1/mcp/servers` | Register a remote MCP server |
| `POST /v1/mcp/servers/{id}:connect` | Begin OAuth 2.0 flow (dynamic client registration) |
| `GET  /v1/mcp/servers/{id}/callback` | OAuth consent callback |
| `POST /v1/mcp/servers/{id}:discover` | Discover and register tools |
| `POST /v1/mcp/servers:generate` | Generate an MCP server from an OpenAPI spec |
| `GET  /v1/mcp/tools` | Tools available **to the calling principal** |
| `POST /v1/mcp/tools/{id}:invoke` | Invoke with trust-tier authorization |
| `POST /v1/mcp/servers/{id}/grants` | Share via owner / role / user grants |

Plus the MCP protocol surface itself at `/mcp/sse` and `/mcp/http`, exposing
`memory.search`, `memory.write`, `context.compile`, and `context.explain` as tools — so
any MCP client can use Mnemos as its memory layer.

```json
// POST /v1/mcp/tools/{id}:invoke → 403
{
  "type": "https://mnemos.dev/problems/trust-tier-violation",
  "title": "Tool invocation denied by trust tier",
  "status": 403,
  "detail": "Tool 'send_email' requires min_trust_tier 2 (user); the motivating context contained tier 5 (retrieved_untrusted) content.",
  "instance": "/v1/mcp/tools/018f…:invoke",
  "trust_tier_required": 2,
  "trust_tier_actual": 5,
  "motivating_bundle": "sha256:9f2c…",
  "offending_sources": [ { "kind": "chunk", "id": "018f…", "document": "scraped_page.pdf" } ]
}
```

This is the prompt-injection defence made observable. The error names the exact document
whose presence in context demoted the trust tier — which is what turns an abstract
security property into something an engineer can act on.

## 8. Error contract

RFC 9457 Problem Details, one shape everywhere:

```json
{
  "type": "https://mnemos.dev/problems/budget-exceeded",
  "title": "Token budget cannot satisfy section floors",
  "status": 422,
  "detail": "Section floors total 6500 tokens but the budget is 4000.",
  "instance": "/v1/context:compile",
  "request_id": "018f3c1e-…",
  "errors": [ { "field": "sections.memory.floor_tokens", "issue": "floor_exceeds_remaining_budget" } ]
}
```

| Status | Used for |
|---|---|
| `400` | Malformed syntax |
| `401` | Missing/invalid credential |
| `403` | Authenticated but not authorized — includes the deciding `rule_id` |
| `404` | Not found **or** not visible. Deliberately indistinguishable (see below). |
| `409` | Idempotency-key conflict, or bitemporal overlap constraint violation |
| `422` | Semantically invalid — the common case for unsatisfiable budgets |
| `429` | Rate/concurrency limit. Always with `Retry-After`. |
| `503` | Dependency unavailable and no degraded path exists |

**`404` for unauthorized resources is intentional.** Returning `403` for a resource that
exists but is invisible confirms its existence — an enumeration oracle. The audit log
records the true `deny` outcome with the rule ID; the client sees `404`. Security and
debuggability are both served, in the places each belongs.

`request_id` is present on every error and equals the trace ID, so a user-reported
failure maps to a trace without a search.

## 9. Data subject requests

| Endpoint | Purpose |
|---|---|
| `POST /v1/dsr/export` | Async export of everything about a subject |
| `POST /v1/dsr/erase` | Hard erase; irreversible; requires elevated permission |
| `GET /v1/dsr/requests/{id}` | Status and the manifest of what was affected |

Erasure cascades through memory claims, embeddings, graph nodes, bundle items, and
object-store artifacts, then re-embeds any derived summary that referenced erased
content — because a summary generated from erased data still contains it. Skipping the
re-embedding step is the most common way erasure silently fails.

## 10. Pagination, caching, limits

**Cursor pagination only.** Opaque, signed cursors encoding `(sort_key, id, filter_hash)`.
Offset pagination is not offered: it drifts under concurrent writes and degrades to a
full scan at depth.

```json
{ "items": [], "next_cursor": "eyJzIjoi…", "has_more": true }
```

Total counts are not returned by default. `COUNT(*)` over a partitioned, RLS-filtered
table is expensive and almost never load-bearing; `?include_total=true` is available and
documented as slow.

**Caching.** Bundles are immutable and content-addressed:
`Cache-Control: public, max-age=31536000, immutable`. Mutable resources use `ETag` +
`If-None-Match`. Conditional writes use `If-Match` and return `412` on mismatch.

**Rate limits** are returned on every response:

```http
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 594
X-RateLimit-Reset: 1785000000
```

Separate buckets for request rate, compute units, and concurrent compilations — because
one expensive compilation and a thousand cheap reads are different kinds of load, and a
single counter cannot express that.

## 11. Realtime

`wss://…/v1/realtime?token=<jwt>` — JWT validated at handshake **and** re-validated on
token expiry, with the connection closed on revocation.

| Topic | Payload |
|---|---|
| `bundle.{job_id}` | Async compilation progress and completion |
| `run.{run_id}` | Agent state transitions, checkpoints, approval requests |
| `document.{doc_id}` | Ingestion progress |
| `dsr.{request_id}` | Export/erase progress |

Server→client only. Client commands go over REST, so authorization has exactly one
implementation rather than two that drift.
