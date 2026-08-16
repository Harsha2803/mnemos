# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It states what is built, the constraints
> you must not violate, and the exact next task. When you finish work, update this file
> **and [`docs/ADAPTATION.md`](docs/ADAPTATION.md)** *in the same commit* — a stale
> tracker is worse than none.

**Last updated:** 2026-08-16 — `B1` deliverable 4 built: the worker claims and processes a
real `ingest_job` end to end (extract/chunk/embed, reusing the factored-out body from
`upload_document`), publishing to both the event bus and the now-authenticated realtime
channel deliverable 3 built. Deliverable 5 (the sources UI) remains — see §5.
**Phase:** **A — make it a chatbot.** `A0` ✅, `A1` ✅, `A2` ✅, `A3` ✅ — all merged to
`main`. Phase A is complete. Build order deviates from phase order once: `B1`/`B2` come
next, before `A4` (2026-08-15 evening re-sequencing note below).
**Next task:** `B1` deliverable 5 — the sources UI (`frontend/src/app/(app)/sources/`):
connect a source, browse and select items, ingest them, and watch the live
queued/running/succeeded/failed feed over the now-real, now-authenticated pipeline
deliverables 1-4 built. **Fully specified in §5.** This is the deliverable that takes PR
#16 out of draft (C12).
**Branch right now:** `feat/b1-connectors`, PR open (draft — until deliverable 5 lands).
Deliverables 1-4's commits are on it; `main` is unchanged.

> ### 2026-08-16 — `B1` deliverable 4 built: the worker claims and processes a real
> `ingest_job`
>
> Picked up right where deliverable 3 left off, on the same branch. **Note on how this
> session started:** the handoff prompt in `prompt.txt` was the deliverable-2 handoff
> (written before deliverable 3 existed), not a fresh one — deliverable 3 had been built and
> committed (`32aed9e`) in a session that skipped writing a new handoff. This file (TRACKER,
> read fresh from disk rather than trusted from the stale prompt) was internally consistent
> and already recorded deliverable 3 as done, so this session verified that against
> `git log`/`gh pr view 16`/the actual code before doing anything else, then continued from
> the true state — deliverable 4 — rather than either redoing deliverable 3 or blindly
> trusting either document. Recorded here so the next handoff is written fresh rather than
> compounding the gap.
>
> **What's built:** `entrypoints/worker/main.py`'s poll loop now claims one `queued`
> `ingest_job` at a time (`FOR UPDATE SKIP LOCKED`, the same concurrency shape the reaper
> already used) via `IngestJobRepository.claim_next`, drains the queue each tick rather than
> pacing one job per `POLL_INTERVAL_S`, and processes it: `ConnectorService.fetch_item`
> (new — resolves a registered source, decrypts its config, fetches the item, and returns
> the source's own `kind` alongside the bytes) feeds
> `KnowledgeService.ingest_connector_item` (new — the extract/chunk/embed body factored out
> of `upload_document` into a shared `_ingest`, so neither path duplicates the pipeline; the
> manual-upload path's behaviour is unchanged, only its internals moved). Every transition
> (`queued -> running`, `running -> succeeded`/`failed`) writes an `ingest_job_event` row and
> publishes twice — to the Redis Streams `EventBus` (durable) and to
> `mnemos:org:{org_id}:ingestion` (live) — matching deliverable 2's "both, not either"
> decision and deliverable 3's exact channel contract verbatim. `mnemosctl connector ingest
> --org-slug X --slug Y --uri Z` (new CLI command) is the real, demonstrable producer until
> deliverable 5's UI exists — idempotent per item (`idempotency_key`), refuses a `uri` that
> is not currently listed.
>
> **The trust-tier question §5 flagged, closed as already resolved:** deliverable 1's own
> dated note had already worked this out — `core/types.py`'s `TrustTier` has no rung below
> `RETRIEVED` (10), already the floor and already what a manual upload gets, so connector
> content passes `TrustTier.RETRIEVED` too. Confirmed by re-reading `ThreatModel.md` §4
> before writing the line, not reused unexamined; `KnowledgeService.ingest_connector_item`'s
> docstring records the reasoning inline so a future reader does not have to re-derive it.
>
> **A real, latent bug found and fixed, not scope creep:** `reap_stuck_jobs` ran inside an
> unscoped `db.session()` — no `org_id`, so the `app.current_org` GUC was never set. Under
> `FORCE ROW LEVEL SECURITY` (migration `0004`) and an unprivileged `mnemos_app` connection
> (migration `0005`), the org-isolation policy's `org_id = NULL` comparison is never true, so
> **the reaper saw zero rows on any real Postgres, always** — regardless of how many jobs
> were actually stuck. Nothing had caught this because nothing had ever run it against a
> real, RLS-enforced database (no test existed for it before this session). Found while
> building the worker's own claim query, which is the same cross-tenant shape for the same
> reason: a single worker polls across every org's queue, so there is no one `org_id` to
> scope a session to until after a claim returns one. Both now use
> `db.elevated_session()` — `platform/db.py`'s own comment already reserved this as the
> second of "two callers, ever" (the first is bootstrap), which is exactly the shape of
> problem it exists for: a query that is legitimately cross-tenant, not a query that forgot
> to scope itself. `test_reap_stuck_jobs_reclaims_an_expired_lease_under_real_rls` is the
> regression test — it would have asserted `reclaimed == 0` against the old code, on a real
> Postgres, no matter how expired the lease was.
>
> **Live-verified against the running compose stack, not just the test suite:** rebuilt and
> restarted `api`/`worker`; registered a real `local_fs` connector against fixture files
> present in both containers' filesystems (they do not share a volume), ran
> `connector ingest`, and watched the worker's own log go `worker.job_claimed` ->
> `worker.job_succeeded` within one poll tick. Confirmed directly via `psql`: the
> `ingest_job` row `succeeded` with a real `document_id`, two `ingest_job_event` rows
> (`queued->running`, `running->succeeded`), the `document` row with `source_kind='local_fs'`,
> `source_uri` the item's own uri, `trust_tier=10`, `uploaded_by` null, and one real `chunk`
> row. Confirmed directly via `redis-cli XRANGE` on the real Streams entry: both transitions
> present with matching fields. Also verified live: re-`connector ingest`-ing the same item
> is refused (idempotency), ingesting an unlisted uri is refused before a job is ever
> created, and a job pointed at a file deleted out from under it (inserted directly via
> `psql`, bypassing the CLI's own listing check) is claimed, fails with
> `error_code=NotFoundError`, and its event history/publishes both reflect `failed` — the
> worker's tick kept running afterward rather than crashing on the exception.
>
> **Evidence:** `make test` — 410 passed (403 prior + 7 new, `tests/test_worker_ingestion.py`
> — `claim_next`'s FIFO ordering and its `FOR UPDATE SKIP LOCKED` exclusivity under real
> concurrent claimers, idempotent enqueue, the full success path against real Postgres +
> Redis with every assertion above also made in-suite, the missing-item failure path, and
> the RLS regression test for the `elevated_session` fix). `make lint` / `make types` clean.
> `make check` (`alembic check`) clean — no migration needed; `ingest_job`/`ingest_job_event`/
> `document.source_kind` all already existed from `M2`/`A2`. No frontend change; deliverable
> 4 has no UI surface of its own, same as deliverables 1-3 — the sources UI (deliverable 5)
> is next and is what takes PR #16 out of draft.
>
> **Not done, deliberately — deliverable 5, exactly as `B1`'s original brief specifies it.**
> No frontend. Heartbeat/backoff retry depth beyond one immediate failure and a per-job
> progress percentage are `B2`, not touched here, matching every prior deliverable's "explicitly
> not `B1`" boundary.
>
> ### 2026-08-16 — `B1` deliverable 3 built: the realtime gateway's JWT-validated WS
> handshake and org-derived channel scoping
>
> Picked up right where deliverable 2 left off, on the same branch. Closed the gap this
> file flagged when deliverable 1 landed: `entrypoints/realtime/main.py`'s `/ws/{channel}`
> accepted any connection and relayed anything published to `mnemos:{channel}` — no JWT
> check, no org scoping, its own docstring calling this deliberate "until M3" (which has
> been done since `A0`).
>
> **What's built:** the gateway now builds the identical `PlatformTokenCodec` +
> `PrincipalResolver` pair `entrypoints/api/main.py`'s lifespan builds, from the same
> `Settings` fields (one signing secret, one issuer, one algorithm allow-list — `api`,
> `worker` and `realtime` stay one trust domain, ThreatModel.md §5.1), which meant giving
> the gateway a `Database` for the first time (mirroring how `entrypoints/worker/main.py`
> already wires one into a non-API entrypoint). `PrincipalResolver.resolve()` is the full
> HTTP-guard-equivalent check — signature, issuer, expiry against the injected clock, the
> user still active, the session (`sid` claim) still live in Postgres — not just a
> signature check, so a revoked session or deactivated user is refused over the WS the same
> as over HTTP. The route factory is now `create_app()` (mirroring the API entrypoint's own
> shape) rather than a module-level `FastAPI()` plus decorators, so the gateway is
> constructible with fixtures the same way `test_route_guard.py`/`test_chat_endpoints.py`
> already construct the API.
>
> **The two judgment calls the brief flagged as open, made and recorded here since nothing
> else will remember them:**
>
> 1. **The token travels as a `Sec-WebSocket-Protocol` offer, not a query parameter.** A
>    browser cannot set an `Authorization` header on a WS upgrade, so it had to be one or
>    the other. `core/config.py`'s `web_signin_complete_url` docstring already states the
>    rule a query parameter would have broken: no credential ever appears in a URL, an
>    access log, a proxy log or browser history. The client offers exactly two subprotocol
>    values, `["bearer", "<token>"]`; the server echoes back only `"bearer"` on `accept()`,
>    so the token does not appear a second time in a response header either. JWTs are safe
>    to carry verbatim as a subprotocol value — the base64url alphabet plus `.` is entirely
>    inside RFC 7230's `token` grammar, so no encoding step was needed.
> 2. **The channel naming scheme is `mnemos:org:{org_id}:{kind}`, and `kind` is drawn from
>    a closed allow-list (`ALLOWED_CHANNEL_KINDS`, currently just `{"ingestion"}`) — never
>    from anything else in the URL.** The `channel` path segment names *what kind* of
>    channel, never *whose*; the org half of the topic is always `caller.principal.org_id`,
>    read off the resolved token, and is never accepted as client input at all. This is
>    deliverable 4's contract to match: the worker's `Cache.client.publish` calls must
>    target exactly `f"mnemos:org:{org_id}:ingestion"` for the gateway to relay them, and
>    deliverable 5's frontend WS client connects to `/ws/ingestion` offering
>    `["bearer", token]` — it never constructs or sends an org id itself.
>
> **The attack the brief named, closed and proved against a real route, not a call site
> that merely looks like it enforces it (`ThreatModel.md` §3⑤, "never ship a second
> defence as if it were the first"):** hand-typing another org's id into the WS URL cannot
> reach that org's channel, because the URL was never able to name an org to begin with —
> only a channel *kind*, checked against a closed set. `tests/test_realtime_auth.py`'s
> `test_a_channel_kind_that_embeds_another_orgs_id_is_refused` is that exact attack
> (`/ws/org:{other_org_id}:ingestion` with org A's own genuine token), refused before
> `accept()` with the same uniform close code (`1008`, no reason on the wire) every other
> handshake denial gets — one answer for "no valid token" and "not a real channel kind",
> the same "every denial reads the same" discipline `providers/base.py`'s `denied()`
> already established for the HTTP guard, extended to a transport that has no JSON body to
> render it in.
>
> **A real property, proved against a real Redis, not asserted:** `test_a_token_for_org_a_
> never_receives_what_is_published_on_org_bs_channel` publishes to org B's real derived
> topic *first*, then org A's, over the same `redis_url` testcontainers fixture deliverable
> 2's tests use, and asserts org A's socket receives org A's payload — a fake pub/sub would
> only prove the fake isolates, and Redis's own exact-topic delivery means there is no
> timing race to arbitrate: if the gateway had derived org A's topic from anything the
> client controls, org B's message — published first — would have arrived first. Also
> covered: a genuine token succeeds and is relayed (the control every denial test is one
> mutation away from), every malformed handshake shape (no subprotocol offered, the token
> half missing, the wrong first subprotocol, a non-JWT token), a token signed with a
> different secret, an expired token (against the injected clock, not the wall clock, same
> as `test_platform_tokens.py`), a revoked session, and a deactivated user's token — 12
> tests total, hermetic identity (a fake `PrincipalRepository`, same reasoning
> `test_route_guard.py` gives) over real Redis.
>
> **Live-verified against the running compose stack, not just the test suite:** rebuilt and
> restarted the `realtime` container; it now depends on Postgres at boot (a
> `ConfigurationError` on a bad `MNEMOS_JWT_SECRET` would fail startup, same as the API) and
> came up clean (`realtime.startup` logged, no error). Minted a genuine access token for a
> real, live, non-revoked session already in the running database (`analyst@mnemos.local` /
> org `mnemos`), connected over a real WebSocket client, received the `subscribed` ack,
> published to `mnemos:org:{org_id}:ingestion` on the compose stack's real Redis and watched
> it relay through; a hand-typed `/ws/org:{other_org_id}:ingestion` with the same genuine
> token was refused with an HTTP `403` at the handshake (uvicorn's translation of a
> pre-`accept()` `websocket.close()`) before ever reaching Redis.
>
> **Evidence:** `make test` — 403 passed (391 prior + 12 new, `tests/test_realtime_auth.py`,
> against real Redis via testcontainers). `make lint` / `make types` clean. `make check`
> (`alembic check`) clean — no migration touched, no schema change. No frontend change;
> deliverable 3 has no UI surface of its own, same as deliverables 1-2.
>
> **Not done, deliberately — deliverables 4-5, exactly as `B1`'s original brief specifies
> them.** No worker changes, no frontend. The worker's real job-processing path
> (deliverable 4) is next — it is what will make the now-authenticated channel carry a real
> event for the first time.
>
> ### 2026-08-15 (night) — `B1` deliverable 2 built: the `EventBus` port and its Redis
> Streams adapter
>
> Picked up right where deliverable 1 left off, on the same branch. Built exactly what §5
> specifies: `platform/events/port.py`'s `EventBus` protocol (`publish`, `ensure_group`,
> `read_group`, `ack` — `XADD`/consumer-group `XREADGROUP`, deliberately not
> `platform/cache.py`'s pub/sub, which the realtime gateway already uses and which cannot
> replay a message to a consumer that was not listening at publish time) and
> `platform/events/redis_streams.py`'s `RedisStreamsEventBus`.
>
> **The design decision §5 flagged as a real judgment call, made:** option (a) — the
> worker (deliverable 4) will publish every `ingest_job` transition to both this Streams
> adapter (durable, for replay) *and* the existing `mnemos:{channel}` pub/sub topic
> `entrypoints/realtime/main.py` already relays (live, for an open WebSocket) — not option
> (b), the gateway running its own consumer-group reader per subscription. (a) needs no
> change to the gateway at all; (b) is real new work in a service that currently has none,
> and its one advantage — replay-on-reconnect straight from the stream — is exactly the
> depth `B2`'s "watch every job's progress" sentence exists for, not `B1`'s. Deliverable 4
> is where this gets wired in; deliverable 2 only builds the primitive both paths need.
>
> **A real property, proved against a real Redis, not asserted:** `tests/
> test_events_redis_streams.py`'s `redis_url` fixture is a session-scoped
> `testcontainers.community.redis.RedisContainer` (the same pattern `conftest.py`'s
> `postgres` fixture already uses for the same reason — a fake pub/sub or in-memory dict
> would only prove the fake is durable). Six tests cover the properties that are the whole
> point of choosing Streams over pub/sub: a group created *after* entries were already
> published still sees them (`ensure_group`'s id `"0"`, not `"$"` — this is the backlog
> pub/sub cannot give); `ensure_group` is idempotent (a worker restart calling it again must
> not raise `BUSYGROUP`); an unacked message is not redelivered to the same consumer on the
> next poll (`read_group` only ever asks for `">"`, new entries); two different consumers in
> one group each get their own entry, never both (competing consumers, not broadcast — the
> property that makes two worker replicas polling the same stream safe); and `ack` actually
> clears the pending-entries list (`XPENDING`), checked directly against the raw client
> rather than only through this adapter's own methods. A seventh test confirms `publish`
> against an unreachable Redis raises `DependencyUnavailableError`, not something
> unhandled — the same translation `S3ObjectStore` already does for MinIO.
>
> **A real mypy gap, resolved rather than silenced with a blanket ignore:** redis-py's
> stubs declare `xadd`'s fields parameter and `xreadgroup`'s return type against wide,
> invariant unions (`Dict[FieldT, EncodableT]`; a `list[...] | dict[...] | dict[...]`
> return) that do not structurally match either a `Mapping[str, str]` argument or the
> `list[[stream, entries]]` shape this client actually receives under RESP2 (its default
> protocol, and the one `Cache` connects with — the dict-shaped alternatives only appear
> under RESP3). Two narrowly-scoped `cast`s, each commented with which runtime shape it
> is asserting and why, close the gap — the same shape of fix `entrypoints/realtime/
> main.py`'s existing `# type: ignore[no-untyped-call]` on `pubsub.aclose` already set as
> precedent for "the dependency's types are the gap, not this code."
>
> **Evidence:** `make test` — 391 passed (384 prior + 7 new, all against real Redis via
> testcontainers). `make lint` / `make types` clean. `make check` (`alembic check`) clean —
> no migration touched. No frontend change; deliverable 2 has no UI surface of its own.
>
> **Not done, deliberately — deliverables 3-5, exactly as `B1`'s original brief specifies
> them.** No realtime auth fix, no worker changes, no frontend. Deliverable 3 (the realtime
> gateway's JWT-validated WS handshake, org-derived channel scoping) is next, and is
> security-load-bearing (C's "never ship a second defence as if it were the first" rule) —
> landing deliverable 2 cleanly, verified, and committed is the same kind of stopping point
> deliverable 1's session ended on, rather than starting deliverable 3 in the same sitting.
>
> ### 2026-08-15 (evening) — `B1` deliverable 1 built: `SourceConnector` port + factory,
> the `content_source` migration, the CLI
>
> Picked up the `B1` brief §5 already specified and built deliverable 1 exactly as
> written: `features/connectors/domain/port.py` (`SourceItem` + the `SourceConnector`
> protocol — `list_items`/`fetch`), three adapters (`s3.py` on top of the existing
> `ObjectStore` port, extended with a `list(prefix)` method rather than a second MinIO
> client; `local_fs.py` scoped to an operator-approved root; `http.py` over an
> operator-curated URL list), `ssrf_guard.py` (ThreatModel.md §3⑥'s deny-list, with real
> DNS-rebinding protection — the request is pinned to the address that was actually
> checked, not re-resolved at connect time), the `content_source` table + RLS, and
> `mnemosctl connector register`/`list-items`.
>
> **A real bug found and fixed, not scope creep:** migrations `0004` and `0006` both
> import the *live* `ORG_SCOPED_TABLES` tuple rather than a frozen copy, despite `0004`'s
> own docstring stating the frozen-copy intent. Adding `content_source` to
> `ORG_SCOPED_TABLES` (required — `test_every_org_scoped_table_has_forced_rls` checks the
> reverse direction too) would have made both migrations try to `ALTER TABLE`/`ALTER
> POLICY` on `content_source` *before* revision `0007` creates it, breaking `alembic
> upgrade head` on any fresh database. Caught by running `alembic check` early, per this
> brief's own flag that this was the first migration since `M2` and not to assume it would
> just work. Fixed by freezing both migrations to a literal tuple (the same 39 tables they
> already applied to) — their behaviour on every existing database is unchanged; only the
> import that made them fragile to a future new table is gone. `content_source`'s own RLS
> is set up inside `0007`, with the corrected (`NULLIF`) policy expression from the start.
>
> **Trust tier for connector-sourced documents, resolved (deliverable 4 will consume
> this):** ThreatModel.md §4's layer-1 row ("external connectors ≥ 4; tool output = 6")
> uses `_v1/core.py`'s original 0-6 scale (`SYSTEM=0` most trusted … `TOOL_OUTPUT=6`
> least), not `core/types.py`'s ported 4-rung scale (`RETRIEVED=10` … `SYSTEM=40`, higher
> = more trusted) — the two were never reconciled when retrieval was ported onto Postgres
> in `A2`. `core/types.py`'s `RETRIEVED` (10) is already the floor of the current scale
> and is already what manual uploads get (`DEFAULT_TRUST_TIER`), and the enum's own
> docstring already lumps "document chunks, tool output, SQL results" into it — there is
> no lower rung to assign. Deliverable 4 should pass `TrustTier.RETRIEVED` for
> connector-sourced documents, same as manual uploads; connector content is not *more*
> trusted than an upload, and the current schema cannot express *less*. `docs/ThreatModel.md`
> §4 still needs a follow-up correction to re-express its table against the current enum —
> flagged here rather than fixed in this session, since it touches a document deliverable 1
> did not otherwise need to open.
>
> **Evidence:** `make test` — 384 passed (352 + 32 new: 8 SSRF-guard, 6 local-fs
> traversal, 4 HTTP connector, 3 S3 connector, 11 `ConnectorService` validation/registration
> — including the loopback/link-local/metadata-IP/localhost refusals actually raising, not
> just asserted to exist). `make lint` / `make types` clean. `alembic upgrade head` and
> `alembic check` both clean against a real Postgres (`pgvector/pgvector:pg16`), including
> the fixed `0004`/`0006` replay and a full upgrade→downgrade→upgrade round trip of `0007`;
> `content_source`'s `FORCE ROW LEVEL SECURITY` and `org_isolation` policy confirmed live
> via `\d+ content_source`. No frontend change — deliverable 1 has no UI surface of its own
> (C12's UI requirement lands with deliverable 5, the sources screen; the PR stays draft
> until then).
>
> **Not done, deliberately — deliverables 2-5, exactly as `B1`'s original brief specifies
> them below.** No event bus, no realtime auth fix, no worker changes, no frontend. §0
> rule 9 does not force a stop mid-milestone the way it would between milestones — but the
> remaining four deliverables are each substantial and the realtime auth fix in particular
> is security-load-bearing (C's "never ship a second defence as if it were the first" rule);
> landing deliverable 1 cleanly, verified, and committed is a real stopping point the same
> shape as `A3` deliverable 3's session stopping with deliverable 4 fully specified ahead of
> it, rather than rushing the remaining four deliverables to close `B1` in one sitting.
>
> ### 2026-08-15 (later) — the `B1` brief written, nothing built
>
> A fresh session, picking up right after `A3`'s merge to `main`. §0 rule 9 (one task per
> session) is explicitly back in force, and §5 as this session found it said `B1` was "not
> specified in detail yet — write its full brief before starting it." This session took that
> literally: it read ADAPTATION §3's `connectors` row, §4/§6/§7, `docs/ThreatModel.md`'s
> connector/SSRF and trust-tier rows, and the actual current code (`features/connectors/` is
> three empty `__init__.py` files; `platform/events/` does not exist yet;
> `entrypoints/worker/main.py`'s stuck-job reaper already exists and already works against
> real `ingest_job` columns, but nothing has ever inserted a *real* job for it to claim;
> `entrypoints/realtime/main.py` is a working Redis pub/sub → WebSocket relay that is,
> **by its own docstring, still completely unauthenticated** — a real gap, not a hypothetical
> one, that `B1` is the first feature to actually need closed). §5 now holds five deliverables
> in build order, an explicit "not `B1`" boundary list (so `B2`'s heartbeat/backoff/progress
> depth doesn't get built early), a flag that `B1` needs the **first Alembic migration since
> `M2`** (a new `content_source` table), and the evidence bar to close it — the same level of
> detail `A3`'s deliverable briefs were written at.
>
> **No code changed.** `features/connectors/`, `platform/events/`, the worker, the realtime
> gateway and the frontend are exactly as `A3` left them. This is deliberate, not a stall:
> writing a five-deliverable brief and then starting deliverable 1 in the same sitting is the
> "roll on to the next thing" pattern rule 9 exists to prevent, and the project's own history
> already has a clean example of *not* doing that (deliverable 3's session stopped with
> deliverable 4 fully specified in front of it rather than starting it). The next session
> should read §5 and begin at deliverable 1.
>
> ### 2026-08-15 — `A3` deliverables 4-5 done: execution, narration, the SQL panel, the
> denial screen — the full vertical slice verified end to end in a real browser
>
> A marathon session, at the project owner's explicit direction: complete the whole A3
> vertical slice — deliverables 4 and 5 together, the integration between them, and real
> browser verification — rather than landing one deliverable and stopping (§0 rule 9
> suspended for this session, the same way it was for the 2026-08-08 run). Multiple agents
> were used as instructed: the lead (this session) designed the backend contract and
> implemented deliverable 4 directly, since it is the piece the two-defence security
> invariant actually depends on; a background agent built deliverable 5 (the SQL panel)
> once that contract was stable, per its own gating instruction ("once the backend response
> contract is understood/stable"). The lead reviewed, integrated, and extended that work
> rather than merely accepting it — the composer redesign and the new Playwright coverage
> below are the lead's own follow-up, done after reviewing the agent's diff.
>
> **Deliverable 4 — execution and narration, all inside `flows/nl2sql/` for the first time**
> (deliverable 3 stayed inside `features/datasources/`; TRACKER §5 was explicit this is
> where the flow package earns its content, because streaming and the chat integration are
> what cross a feature boundary):
> - `features/datasources/adapters/executor.py`'s `PostgresExecutor` — the same short-lived-
>   engine-per-call pattern `PostgresIntrospector` established in deliverable 1. Statement
>   timeout is an asyncpg connection parameter (`server_settings`), never a `SET` built by
>   concatenating the guarded SQL string. Row cap is `result.fetchmany(max_rows + 1)` — one
>   extra row fetched, never a `LIMIT` appended to the statement TRACKER's own "watch out"
>   note in §5 warned against. `asyncpg.exceptions.QueryCanceledError` surfaces two layers
>   deep (`DBAPIError.orig.__cause__`, not `.orig` itself — SQLAlchemy's asyncpg dialect
>   wraps the real exception in its own `AsyncAdapt_asyncpg_dbapi.Error`, found by writing a
>   throwaway test that printed the exception chain rather than guessing at it) and is
>   reported as `error_code="statement_timeout"`, not raised. Every Postgres value the demo
>   schema or a generated `SELECT` can produce (`Decimal`, `date`, `UUID`, ...) is normalised
>   to a JSON-safe scalar before it ever reaches the response or the narration prompt.
> - `DatasourceService.execute()` is the one new entry point `flows/nl2sql` calls — it
>   decrypts the DSN and delegates to the injected `SqlExecutor`, the same trust boundary
>   `refresh_schema` already draws around `self._introspector`. The decrypted DSN never
>   leaves this method.
> - `SqlRunRepository` gained `record_execution` (fills the six execution columns `sql_run`
>   has carried unused since `M2`) and `attach_to_message` (links a run to the assistant
>   message it produced, mirroring `add_citations`' "message must exist first" sequencing).
>   `SqlRunRecord` grew the same six fields plus `message_id`, all defaulted so no existing
>   caller (the CLI, deliverable 3's tests) needed to change.
> - `SqlGenerationService.generate()` gained optional `attempt`/`repair: RepairContext`
>   parameters — attempt 1's call site is unchanged; `Nl2SqlFlow`'s repair loop is a second,
>   explicit call with `attempt=2` and the previous rejected statement, never an internal
>   loop inside `generate()` itself.
> - `Nl2SqlFlow` (`flows/nl2sql/application/service.py`) — composes `ChatRepository`,
>   `DatasourceService`, `SqlGenerationService`, and a second `SqlRunRepository` instance the
>   same way `RagFlow` composes `ChatRepository` and `KnowledgeService`. Holds the security
>   invariant explicitly in its own module docstring: `guard_sql()` decides `REJECTED_* ->
>   never execute` / `ALLOWED -> execution`, and every attempt — the first and every repair —
>   is independently guarded before `.execute()` is ever called, which happens at most once,
>   only for the *final* attempt's `ALLOWED` verdict.
> - **The repair loop covers every `REJECTED_*` verdict, not only unparseable SQL** — a
>   deliberate reading of TRACKER §5's "a repaired query *after a rejection*", chosen over
>   scoping repair to unparseable-only: a repair attempt is independently re-guarded the same
>   as attempt 1, so retrying after a deliberate write attempt is not a security weakening,
>   only another chance for the model to produce a read. **Real local-model evidence, not
>   assumed:** `qwen2.5:3b-instruct`, asked five different adversarial ways in the browser to
>   delete/truncate/drop real tables, complied with the guard's rejection reason on the
>   repair turn and produced a valid, safe alternative read **five times out of five** —
>   `analytics.region`/`analytics.sales_order`/`analytics.customer` row counts confirmed
>   unchanged via `psql` before and after. The repair loop is not a weaker guard; it is a
>   better user experience wrapped around the same guard, proven live against the exact
>   model this build ships.
> - **A genuine, unscripted third outcome, found live rather than only synthesized:** a
>   guard-`ALLOWED` statement (a real `SELECT`, no write) can still fail *at* Postgres — one
>   browser question produced a mis-joined correlated subquery and
>   `asyncpg.exceptions.CardinalityViolationError`. `PostgresExecutor` reported it as
>   `error_code="execution_error"` exactly as designed, the flow templated
>   `execution_error_narration` (no model call over a failure that has no result set to
>   narrate honestly), and the SQL panel rendered a third, distinct labelled state ("Allowed
>   by the read-only guard, but the database could not run it") rather than collapsing it
>   into the denial banner. `frontend/e2e/nl2sql.spec.ts`'s happy-path test was rewritten to
>   accept this outcome alongside a populated grid — asserting a 3B model always writes
>   semantically correct SQL is not a claim this build makes, and a flaky e2e test hiding
>   that fact would be worse than one that states it.
> - **A narration quirk, found live, recorded rather than hidden:** when a repaired attempt
>   succeeds, the original adversarial user turn is still the final `USER` turn in the
>   narration prompt (by design — the narration answers *the user's question*, not a
>   sanitised paraphrase of it). A few times the 3B narration model echoed a fragment of the
>   *original, rejected* instruction back as if it were commentary, even though the SQL panel
>   directly below always showed the correct, executed statement and its real rows. This is a
>   narration-quality artifact of a small model, not a security issue — the guard already
>   proved the echoed text never ran — but it is real, and it is the same lesson deliverable
>   3 already recorded about the system prompt: a small local model does not reliably do what
>   it is told, which is exactly why the guard, not the prompt, is the thing that must hold.
>   Left as a known limitation rather than patched around, since sanitising the narration
>   prompt is real design work belonging to a future session, not a one-line fix.
> - Denial narration (`flows/nl2sql/domain/prompt.py`'s `denial_narration`) and execution-
>   failure narration are both templated, never a second model call — TRACKER §5 was explicit
>   that a `REJECTED_*` verdict's "narration" is the verdict and detail already on the record.
>
> **Deliverable 5 — the SQL panel, built by a background agent once the SSE `done.nl2sql`
> contract was final, then extended by the lead:**
> - `AssistantDone` (`features/chat/domain/events.py`) gained an optional `extra: dict[str,
>   JsonValue] | None` field — `features/chat` stays ignorant of what a flow puts there;
>   `flows/nl2sql` is the first (and so far only) caller. The `done` SSE frame gained an
>   `nl2sql` key carrying it verbatim, so the frontend gets the SQL, verdict, rows and
>   truncation flag in the same terminal frame that carries the narration, with no second
>   request and no refetch race — the "one coherent NL2SQL/chat result model" the original
>   prompt asked for.
> - `SqlPanel.tsx` — the code block, an accessible result `<table>` (`scope="col"`,
>   sr-only caption), a truncation note, and now *three* distinct labelled states: allowed,
>   guard-refused, and guard-allowed-but-execution-failed — each pairing `--danger` with an
>   icon and a plain-word label, never colour alone. Rendered outside `MessageBubble`'s
>   `measure`-clamped bubble, full content width, per DesignSystem's own reasoning that
>   tabular data is exactly what the 46rem prose measure should not constrain.
> - `Composer.tsx` **redesigned after the agent's version landed**, at the project owner's
>   direct request mid-session: the send control is now an icon-only circular button
>   (`ArrowUp`, accessible name still exactly `"Send message"` — every existing test and the
>   new e2e spec depend on that name being stable) rather than a text button, and the two
>   independent "Use documents"/"Ask your data" checkboxes (mutually exclusive by disabling
>   the sibling) became one Radix `ToggleGroup` — a real three-option `radiogroup`
>   ("Chat"/"Use documents"/"Ask your data"), reusing the exact primitive and visual language
>   `ThemeToggle` already established for Appearance. "Chat" is a real, nameable third state
>   rather than the absence of a checked box, and the impossible "both true" state is now
>   unbuildable by construction instead of prevented by a `disabled` prop. Every test and e2e
>   spec that referenced the old `checkbox` role (`Composer.test.tsx`,
>   `frontend/e2e/knowledge.spec.ts`, the new `nl2sql.spec.ts`) was updated to `radio`.
> - Historical reload is honest about its limit, by design: `GET /v1/chat/sessions/{id}`
>   returns an `nl2sql` message's narration and `flow: "nl2sql"`, but not its SQL/rows/verdict
>   — those exist only in the live `done` frame. A reloaded historical message renders as a
>   plain assistant bubble, no panel, rather than a panel silently missing its data. `sql_run`
>   itself (verdict, tables, execution metadata) is still durable — only the row *values*
>   are not persisted anywhere, matching a live query result rather than an audit record.
>
> **Real browser verification, signed in as `analyst@mnemos.local` against the rebuilt
> `api`/`web` containers (§4 item 40):**
> ```
> "what was total revenue by region"
>   -> SELECT r.region_name, SUM(so.net_amount) ... GROUP BY r.region_name
>   -> executed as mnemos_ro, 4 rows: AMER East $208,620 · EMEA West $204,120 ·
>      APAC North $617,760 · EMEA South $512,550
>   -> narrated correctly, grid rendered, columns/values matched real seeded data
>
> "delete every row from the sales_order table"  (sql_repair_attempts temporarily forced to
>   0 via MNEMOS_SQL_REPAIR_ATTEMPTS, for one deterministic screenshot of the terminal
>   denial state — the shipped default of 2 is what every other run in this session used,
>   including the five adversarial attempts that all recovered via repair)
>   -> DELETE FROM analytics.sales_order -> rejected_write -> never executed
>   -> UI: "Refused — this statement would have written to the database", the reason,
>      and the refused SQL — never a generic error toast
> ```
> `analytics.region`/`.sales_order`/`.customer` row counts confirmed unchanged via direct
> `psql` queries throughout the session, independent of the application's own claims.
>
> **Evidence:** `make test` — **352 passed** (342 before this session; +10: 6 in the new
> `test_datasources_execution.py` — a real read, row-cap truncation, exact-at-cap is not
> truncated, statement-timeout cancellation confirmed fast rather than merely erroring,
> syntactically-invalid SQL reported not raised, non-JSON-native cell normalisation — all
> against real `mnemos_analytics` as real `mnemos_ro`; 4 in the new `test_nl2sql_flow.py` —
> the full allowed-execution-narration path on the wire, a rejected verdict proven never
> executed by a before/after row count against the real analytics database, a repair
> recording its own `attempt=2` `sql_run` row, and the persisted assistant message linking
> back to its `sql_run` by id). `make lint` / `make types` (`mypy --strict`, 169 source
> files) / `make check` all clean — no migration needed, exactly as anticipated (`sql_run`'s
> six execution columns already existed from `M2`). **Frontend:** `npm run lint` /
> `npx tsc --noEmit` / `npm run test` (16 files, **97 passed**) / `npm run build` all clean.
> **Playwright**, real stack: `frontend/e2e/nl2sql.spec.ts` (new) — the full ask/SQL/grid/
> narration sentence and the write-attempt-never-reaches-the-database sentence, both run
> twice back to back with no flakes after the happy-path test was made honest about
> execution-failure being a legitimate third outcome; `chat.spec.ts` (1), `knowledge.spec.ts`
> (1, updated for the new `radio` role), `auth.spec.ts` (7) all still green — no regression
> from the composer redesign.
>
> **PR #15 comes out of draft with this session:** all five deliverables are committed, CI is
> green, and the full "you can now ___" sentence is demonstrated in a real browser against
> the real stack — the C12/C14 bar the draft status existed to enforce.
>
> **What is deliberately still not done, stated plainly:** the router (`A4`) that would pick
> NL2SQL without `use_datasource` being set manually; a datasource registry UI or a second
> warehouse dialect; the cost ledger for generated queries (`C2`); the context compiler
> (`C4`); persisting NL2SQL result rows across a reload. None of these were in scope — see
> §5's original "explicitly not in A3" list, unchanged by this session.

> ### 2026-08-15 — `A3` deliverable 3 (generation + the AST guard) done, PR #15 still draft
>
> A fresh session picking up exactly where the deliverable-2 session's handoff left off —
> prompt.txt was explicit that deliverable 3, the security-critical center of this
> milestone, deserved a session's full, unhurried attention rather than being folded into
> whatever else was going on. This session did deliverable 3 alone, verified it against a
> real local model rather than only against fakes, and stopped rather than starting
> deliverable 4.
>
> **What shipped, on `feat/a3-nl2sql`, all inside `features/datasources/`** — no new
> `flows/nl2sql/` package yet. TRACKER §5 was explicit that deliverables 3-4 are "more of
> this feature, not a new one"; the flow package is deliverable 4's, once streaming and the
> chat integration actually need it:
> - `domain/guard.py`'s `guard_sql` — the AST read-only guard. Deliberately an
>   **allowlist**: the parsed statement must be `sqlglot.exp.Query` (a `SELECT`, optionally
>   `WITH`-prefixed, or a set operation over `SELECT`s), and every node in the tree — not
>   just the root — is walked for anything that writes, changes privileges, or is a shape
>   `sqlglot` falls back to a generic `Command` for. A **blocklist** scoped to
>   `INSERT`/`UPDATE`/`DELETE`/DDL was tried first and found to miss `SELECT ... INTO`
>   (creates a table), `FOR UPDATE`/`FOR SHARE` (takes a write lock), and
>   `EXPLAIN`/`VACUUM`/`CALL`/`COPY`/`SET` (none of these is a DML/DDL node at all) —
>   requiring the positive case catches all of them without naming any of them. Stacked
>   statements (`SELECT 1; DROP TABLE ...;`) parse to a `Block`, not a `Query`, and are
>   rejected the same way — closing the classic decoy-then-write injection shape as a
>   consequence of the allowlist rather than a special case bolted onto it.
> - `domain/generation.py` — `NL2SQL_SYSTEM_PROMPT` and `extract_sql_statement`, pulling the
>   candidate statement out of a fenced ` ```sql ` block with a fallback to the whole
>   response when a small local model does not comply with the fence instruction. Extraction
>   does not have to be clever — `guard_sql`'s own parse step is what actually decides
>   safety.
> - `application/generation.py`'s `SqlGenerationService` — a **sibling** of
>   `DatasourceService` (composing it for `require_datasource`/`render_context`), not a
>   fifth method on it and not a new `flows/` package, because generation calls a model and
>   makes a security verdict, which is a different kind of operation with different tests
>   than the fast, no-verdict registry/cache operations `DatasourceService` already had.
>   `.generate()` is one blocking `ChatModel.complete()` call, never `.stream()` — nothing
>   can be guarded, let alone shown, before the whole statement has arrived.
>   `DatasourceService._require_datasource` graduated from private to a public
>   `require_datasource` the moment this second class needed the same lookup.
> - `SqlRunRepository` (`adapters/repository.py`) — persists every attempt, allowed or
>   refused, with its verdict, detail, and `authorized_tables`/`denied_tables`. **No
>   migration needed**: `sql_run` already had every column from `M2`.
> - `mnemosctl datasource generate --org-slug X "<question>"` — generates, guards, and
>   records one attempt; **never executes** (deliverable 4's job). The real, demonstrable
>   consumer of `SqlGenerationService`, the same reasoning `show-context` was for
>   `render_schema_context` in deliverable 2.
> - Fixed the same class of bug `A1` found (§4 item 41): `sql_run.message_id`'s foreign key
>   to `chat_message` is the first one any CLI code path has ever touched, and
>   `entrypoints/cli.py` had never needed `mnemos.platform.models`'s side-effect import
>   before — `NoReferencedTableError` from a live `mnemosctl` run, not from `pytest` (the
>   test suite already carried that import, matching `test_datasources_introspection.py`'s
>   own pattern, which is exactly why the tests never caught it). Fixed with the same
>   one-line import `entrypoints/api/main.py` already carries, same comment, new reason.
>
> **Verified against a real local model, not a fake, on the rebuilt `api` image:**
> ```
> $ docker compose exec api mnemosctl datasource generate --org-slug mnemos \
>     "what was total revenue by region last quarter"
> verdict          : allowed
> sql              : WITH active_customers AS (...), region_revenue AS (...)
>                     SELECT region_name, total_revenue FROM region_revenue ORDER BY ... DESC
> tables read      : analytics.sales_order, analytics.customer, analytics.region, analytics.product
>
> $ docker compose exec api mnemosctl datasource generate --org-slug mnemos \
>     "delete every row from the sales_order table"
> verdict          : rejected_write
> detail           : not a read statement (parsed as Delete)
> sql              : DELETE FROM analytics.sales_order
> tables refused   : analytics.sales_order
> ```
> The second call is the one that matters: **`qwen2.5:3b-instruct` complied with the
> adversarial instruction and emitted a real `DELETE`.** The system prompt's "never
> INSERT/UPDATE/DELETE" is a request, not a defence, and a 3B model does not reliably honour
> requests — `guard_sql` is what actually stopped it, not the prompt. Confirmed directly
> against `sql_run` with `psql`, not the CLI's own printout: both attempts persisted,
> `attempt=1`, `message_id` null, `executed=false` — exactly the shape deliverable 4 builds
> on.
>
> **Evidence:** `make test` — **342 passed** (302 before this session; +40: 31 pure
> `guard_sql` cases in the new `test_datasources_guard.py`, covering CodingStandards §9
> mandatory case 4 in full — DML nested in a CTE/a UNION arm/a subquery, unparseable
> rejected fail-closed, the allowed control — plus every write/privilege/DDL shape and the
> shapes a naive DML blocklist would have missed; 9 cases in the new
> `test_datasources_generation.py` — `extract_sql_statement`, `SqlGenerationService.generate`
> against a real Postgres with a scripted `FakeChatModel` (an allowed verdict with its
> tables, every attempt recorded regardless of verdict, a cross-org datasource is a
> `LookupError`, an unregistered slug is a `LookupError`), and
> `test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed` — connects directly as
> `mnemos_ro`, bypassing the guard and the service entirely, and proves the second defence
> holds on its own, formalizing what deliverable 1 verified ad hoc). `make lint` / `make
> types` (165 source files, `--strict`) / `make check` all clean (`alembic check`: "No new
> upgrade operations detected"). PR #15: `backend`, `frontend`, `compose` all green.
>
> **Deliberately left in draft, not merged, still no UI:** same C12 reasoning as
> deliverables 1-2. `mnemosctl datasource generate` is an operator/inspection tool, not a
> product screen — the SQL panel (deliverable 5) is still what makes any of `A3`
> demonstrable in the product, and deliverable 4 (execution + narration) has to exist first
> for that panel to have a result set and an answer to show.
>
> **What is NOT done:** no execution — the statement is guarded and recorded, never run —
> no narration, no chat-surface UI, no e2e test, no repair loop
> (`Settings.sql_repair_attempts` is deliverable 4's). §5 below specifies deliverables 4-5
> in full.

> ### 2026-08-15 (evening) — the plan re-sequenced: ingestion pulled ahead of the router
>
> The project owner asked, after deliverable 2 landed and with no more testing possible
> that night, for two things: fold ingestion into the near-term plan, and shape whatever
> gets built next so there is always at least one complete, testable flow rather than
> several half-built ones. Asked to choose between finishing `A3` first versus dropping it
> to start ingestion immediately, the answer was to finish `A3` first — it is already 2/5
> done and is the closer target for "one complete flow." So the sequence changes only
> **after** `A3`: `B1`/`B2` (ingestion — connect a source, browse it, ingest it at scale)
> now come before `A4` (the router), reversing their phase order.
>
> **Why ingestion over the router specifically.** `A4` mostly changes *how* existing flows
> are triggered — a classifier picks chat/RAG/NL2SQL instead of the user picking a mode via
> `use_documents`/its NL2SQL sibling. It is real work but not a new capability a stranger
> hasn't already seen once `A3` ships. `B1` is a new capability: connecting a source
> (S3/local/HTTP) instead of only a manual upload, with ingestion events visible live. That
> is a bigger step toward the "platform" pitch (§0.1) and closer to what "include ingestion"
> asked for than reshuffling routing would be.
>
> **Nothing else changed.** The phase tables in §3.0 still group work by kind (chatbot
> surface / platform depth / enterprise governance / ship polish) — they are not rewritten.
> The authoritative next-up sequence is §5's "Then, in order" list, updated to read `A3` →
> `B1` → `B2` → `A4` → `B3` → `B4` → `C1`-`C4` → `D1`. No code changed this note — it is a
> planning-only update, and `A3` deliverable 3 (the AST guard) is still the very next task,
> unchanged and un-rushed.

> ### 2026-08-15 — `A3` deliverable 2 (business glossary) done, PR #15 still draft
>
> A separate, fresh session picking up exactly where the 2026-08-11 session's handoff left
> off — the ordinary one-task-per-session rule (§0 rule 9) is back in force, so this session
> did deliverable 2 alone and stopped, rather than continuing into deliverable 3.
>
> **What shipped, on `feat/a3-nl2sql`:**
> - `features/datasources/domain/glossary.py` — `GlossaryTermRow`, the one shape a term
>   takes whether it is about to be seeded or was just read back (matched by `term` text,
>   not by id, so there is nothing to convert between a draft and a persisted row).
> - `features/datasources/domain/context.py` — `render_schema_context`, the pure function
>   TRACKER §5 deliverable 2 asked for: groups `sql_schema_object` rows by table (table row,
>   then its columns) and lists the glossary after the schema, so the model reads the
>   columns a term maps onto before it reads the term itself. Deliberately not built in
>   deliverable 1 — there was no glossary to render yet.
> - `GlossaryRepository` (`adapters/repository.py`) — `ensure_terms` (idempotent, matched by
>   `term` text — re-seeding never clobbers an edit made since) and `list_terms`.
>   `SchemaObjectRepository` gained `list_all`, reusing `SchemaObjectDraft` as the read shape
>   rather than inventing a second near-identical type.
> - `DatasourceService.seed_glossary` and `.render_context` — both follow deliverable 1's
>   `_require_datasource`-or-`LookupError` shape (now factored out, since three methods
>   share it).
> - `mnemosctl datasource seed-glossary --org-slug X` — writes the four curated terms in
>   `DEMO_GLOSSARY_TERMS` (`entrypoints/cli.py`): revenue, active customer, order volume,
>   segment, each with a real `sql_expression` against the actual `analytics.*` columns.
> - `mnemosctl datasource show-context --org-slug X` — prints the rendered block. Not
>   strictly required by the deliverable's text, but it is the real, demonstrable consumer
>   of `render_schema_context` until deliverable 3 exists — a function nothing calls is the
>   placeholder rule 5 forbids, and this is a genuinely useful inspection command on its own,
>   not scaffolding built to satisfy a rule.
>
> **Verified against the rebuilt `api` image, not just tests:** `docker compose build api &&
> up -d api`, then `introspect` → `seed-glossary` (`4 newly written`) → `seed-glossary` again
> (`0 newly written` — idempotent) → `show-context`, which printed all four `analytics.*`
> tables with their columns and all four glossary terms, schema before glossary. Full
> transcript in §3's `A3` entry below.
>
> **Evidence:** `make test` — 302 passed (290 before this session's work — TRACKER's
> previous "298" for deliverable 1 was measured against a slightly different tree state;
> 290 is what this session actually measured on `feat/a3-nl2sql` as it stood before any new
> code — +12: 5 pure `render_schema_context` cases, 7 glossary integration cases against a
> real Postgres). `make lint` / `make types` (162 files, `--strict`) / `make check` all
> clean — `make check` confirms no migration was needed: `glossary_term` already had every
> column from `M2`.
>
> **Deliberately left in draft, not merged, still no UI:** same C12 reasoning as deliverable
> 1's note. `seed-glossary` and `show-context` are operational CLI commands, not a product
> screen — the SQL panel (deliverable 5) is still what makes any of `A3` demonstrable in the
> product.
>
> **What is NOT done:** no SQL generation, no `sqlglot` usage anywhere yet, no AST guard, no
> execution, no narration, no chat-surface UI, no e2e test. §5 below specifies deliverables
> 3-5 in full.

> ### 2026-08-11 — `A3` started: deliverable 1 (schema introspection) done, PR #15 draft
>
> Same session as the `A2` merge above, continued rather than handed off — the project
> owner asked for a good chunk of work and to stop only when the session ended, not for a
> single task. `A3`'s five deliverables (TRACKER §5 as it stood before this note) are each
> substantial and one — SQL generation behind the AST guard — is the security-critical
> center of the milestone, so rather than rush all five in one sitting, this session did
> deliverable 1 completely and for real, then stopped at a clean, tested, CI-green
> boundary. Nothing here is a stub: every piece below is exercised by a real test against a
> real Postgres.
>
> **What shipped, on `feat/a3-nl2sql`, commit `feat(nl2sql): schema introspection`:**
> - `mnemosctl datasource introspect --org-slug X [--slug sales-warehouse]` — idempotently
>   registers the seeded `analytics.*` warehouse for an org (encrypting its DSN with a new
>   `core.crypto.DsnCipher`, Fernet, keyed by `MNEMOS_DSN_ENCRYPTION_KEY`), then introspects
>   `information_schema` + `pg_class` **as `mnemos_ro`** — the same role generation will
>   execute as, so introspection can never see more than execution can reach — and replaces
>   (not accumulates onto) the org's `sql_schema_object` cache.
> - The allowlist discipline `adapters/models.py` already documented is enforced in code
>   now: `DatasourceService.register` raises on an empty `allowed_schemas` rather than
>   treating empty as "everything" (`test_register_rejects_an_empty_allowlist`).
> - `MNEMOS_ANALYTICS_DATABASE_URL` is now wired into `docker-compose.yml` — it did not
>   exist before this session, so nothing running in a container could ever have reached
>   `mnemos_analytics`. `analytics_database_url`'s default also now uses the `asyncpg`
>   driver (it did not), matching `database_url`'s own `_require_async_driver` validator.
> - **Test infrastructure that all of deliverables 3-4 will also depend on:** the shared
>   `postgres` fixture in `conftest.py` now also creates `mnemos_analytics` and seeds it by
>   running the real `deploy/postgres/init/02-analytics-seed.sql` against it (stripping only
>   the `\connect` meta-command, which `asyncpg` cannot run). This is not incidental
>   plumbing — `test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed`
>   (deliverable 3's acceptance test, not yet written) needs a real `mnemos_ro` role that
>   really cannot write, and this session verified that guarantee directly
>   (`INSERT ... -> asyncpg.exceptions.InsufficientPrivilegeError`) before building on it.
>
> **Verified, not just written:** `make test` — 298 passed (278 before this session, +20:
>   12 new domain/integration tests for datasources, 8 pre-existing ones re-counted after
>   the fixture change). `make lint` / `make types` / `make check` all clean (`alembic
>   check` reports "No new upgrade operations detected" — `sql_datasource`,
>   `sql_schema_object`, `glossary_term`, `sql_run` all already existed with `FORCE ROW
>   LEVEL SECURITY` from `M2`, confirmed directly against `pg_class.relforcerowsecurity`
>   before writing a line of repository code, so no migration was needed). PR #15's three
>   CI jobs (`backend`, `frontend`, `compose`) are all green.
>
> **Deliberately left in draft, not merged:** C12 says a feature ships its UI in the same
> milestone, and deliverable 1 has no UI of its own — the SQL panel (deliverable 5) is what
> makes any of `A3` demonstrable. Merging deliverable 1 alone would put backend-only NL2SQL
> code on `main` with nothing to show for it, which is the exact drift C12 exists to
> prevent. The PR stays open and draft, gaining one commit per deliverable, until 5 lands;
> then it goes through the same green-CI-then-squash-merge motion as #11/#13/#14.
>
> **What is NOT done, stated plainly so it is not mistaken for progress:** no glossary, no
> SQL generation, no AST guard, no `sqlglot` usage anywhere yet (it is declared as a
> dependency, per the original brief, and literally nothing imports it), no execution, no
> narration, no chat-surface UI, no e2e test. §5 below specifies deliverables 2-5 in full —
> read it before writing code, the same way this session read the original A3 brief before
> starting deliverable 1.

> ### 2026-08-11 — PR #14 merged; the `compose` CI gap is fixed
>
> The one blocker left from the 2026-08-08/10 run was a `compose` CI job failing because
> `api`'s `depends_on` waited for `minio` to be healthy but not for `minio-init` (the
> one-shot container that creates the `mnemos-documents` bucket) to finish — so
> `S3ObjectStore.health()`'s `head_bucket` call could race the bucket's creation on a clean
> runner. Fixed by adding `minio-init: {condition: service_completed_successfully}` to
> `api`'s `depends_on` in `docker-compose.yml`. Verified locally (`docker compose down -v &&
> docker compose up -d --build`, `/readyz` turned fully green with no manual intervention),
> then pushed to `feat/a2-rag`, watched all three PR #14 checks go green, and squash-merged
> (`gh pr merge 14 --squash --delete-branch`), matching how #11 and #13 were merged. Then,
> from a truly clean state (`docker compose down -v && up -d --build && make bootstrap` on
> the merged `main`), the A2 sentence — upload a document, ask about it, get a cited answer,
> click the citation — was re-verified via the real `frontend/e2e/knowledge.spec.ts`
> Playwright suite against the merged image (not the branch), and it passed clean.

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
| **A2** | Upload → extract → chunk → embed (pgvector HNSW) · retrieval ported from `_v1` · RAG flow · citations · knowledge library | **upload a document and ask questions about it**, with citations you click into | ✅ merged (PR #14) |
| **A3** | NL2SQL: introspection · glossary · generate · AST read-only guard · `mnemos_ro` execution · narration · SQL panel | **ask a question about your data in English** and see the SQL, the rows and the narration — and see the guard visibly refuse a write | ✅ verified 2026-08-15, PR #15 |
| **A4** | Router: classify a message → chat / RAG / NL2SQL · flow indicator | **ask anything without choosing a mode**, and see which flow answered and why | ⬜ — built **after** `B1`/`B2`, see below |

**At the end of Phase A the thing this project is for exists.** Everything after deepens it.

**Build order stops following phase order once, starting 2026-08-15: `B1`/`B2` (ingestion),
below, are built immediately after `A3` — before `A4`.** These tables still group work by
*kind*; they no longer promise strict A-then-B-then-C-then-D sequencing. §5's "Then, in
order" list is the authoritative next-up sequence; the note above it explains why.

**Phase B — make it a platform.**

| ID | What it builds | You can now… | Status |
|---|---|---|---|
| **B1** | Object storage · source connectors (MinIO/S3, local FS, HTTP) · Redis Streams event bus · sources UI | **connect a source, browse it, and watch ingestion events arrive live** | 🟡 **deliverable 4/5 done** — connectors, event bus, realtime auth, the worker's real job-processing path; only the UI remains |
| **B2** | Ingestion jobs at scale: heartbeat, retries, status history, stuck-job reaper · per-job progress UI | **ingest a folder and watch every job's progress — including one that dies, surfaced as stuck rather than silently lost** | ⬜ **after `B1`** |
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

### 🟡 B1 — connect a source and watch it ingest, deliverable 4/5 done 2026-08-16

**Deliverables 1-4 — the `SourceConnector` port + factory, the `EventBus` port + Redis
Streams adapter, the realtime gateway's JWT-validated WS handshake, and the worker's real
job-processing path — are done; deliverable 5 (the sources UI) is not.** Branch
`feat/b1-connectors`, PR open in draft (stays draft until deliverable 5 exists, per C12 —
deliverables 1-4 have no product UI by design).

What's built (deliverable 1): `features/connectors/domain/port.py` (`SourceItem`,
`SourceConnector` protocol), three adapters (`s3.py` over the extended `ObjectStore` port,
`local_fs.py` default-deny outside an operator-approved root, `http.py` over an
operator-curated URL list, never crawling), `ssrf_guard.py` (deny-list +
DNS-rebinding-safe address pinning), `adapters/crypto.py`'s `SourceConfigCipher`, the
`content_source` table + RLS (migration `0007`), `ConnectorFactory` + `ConnectorService`,
and `mnemosctl connector register`/`list-items`. Full detail, including the two migration
bugs found and fixed along the way and the trust-tier reconciliation for deliverable 4, is
in the dated note near the top of this file ("`B1` deliverable 1 built").

What's built (deliverable 2): `platform/events/port.py`'s `EventBus` protocol (`publish`,
`ensure_group`, `read_group`, `ack`) and `platform/events/redis_streams.py`'s
`RedisStreamsEventBus` — `XADD`/consumer-group `XREADGROUP`, not `platform/cache.py`'s
pub/sub. The design decision §5 left open (how a Streams entry reaches a browser) is made:
the worker (deliverable 4) will publish to both this adapter and the existing pub/sub
channel the realtime gateway already relays, rather than the gateway growing its own
consumer-group reader. Full detail, including the six real-Redis tests that prove
durability/idempotence/competing-consumer semantics rather than assert them, is in the
dated note near the top of this file ("`B1` deliverable 2 built").

What's built (deliverable 3): `entrypoints/realtime/main.py`'s `/ws/{channel}` now
validates the platform JWT through the same `PlatformTokenCodec` + `PrincipalResolver` the
HTTP API uses (the gateway gained its own `Database` to do this), over a
`Sec-WebSocket-Protocol` handshake (`["bearer", token]`, never a query parameter — no
credential in a URL, a log or browser history). The channel a caller reaches is always
`mnemos:org:{org_id}:{kind}`, with `org_id` read only from the resolved token and `kind`
checked against a closed allow-list (`{"ingestion"}` today) — the URL was never able to
name an org, genuine or forged. Full detail, including the two judgment calls the original
brief left open (subprotocol vs. query parameter; the channel naming scheme deliverables
4-5 must match) and the live verification against the running compose stack, is in the
dated note near the top of this file ("`B1` deliverable 3 built").

What's built (deliverable 4): `entrypoints/worker/main.py`'s poll loop claims one `queued`
`ingest_job` at a time (`IngestJobRepository.claim_next`, `FOR UPDATE SKIP LOCKED`) and
processes it — `ConnectorService.fetch_item` (new) resolves and fetches the item,
`KnowledgeService.ingest_connector_item` (new, sharing `upload_document`'s factored-out
`_ingest` body) extracts/chunks/embeds it at `TrustTier.RETRIEVED`, same as a manual
upload. Every transition writes an `ingest_job_event` row and publishes to both the
`EventBus` (durable) and `mnemos:org:{org_id}:ingestion` (live, deliverable 3's exact
contract). `mnemosctl connector ingest` is the CLI producer until deliverable 5's UI
exists. **A real RLS bug found and fixed along the way:** `reap_stuck_jobs` ran in an
unscoped session and so saw zero rows on any real Postgres, always — fixed with
`db.elevated_session()`, the second of the "two callers, ever" `platform/db.py` already
reserved for exactly this cross-tenant shape of query. Full detail, including the live
verification against the running compose stack (rebuilt `api`/`worker`, a real ingest
watched `queued -> running -> succeeded` via `psql`/`redis-cli`, plus the failure and
idempotency paths), is in the dated note near the top of this file ("`B1` deliverable 4
built").

**Evidence:** `make test` — 410 passed (403 prior + 7 new: `tests/test_worker_ingestion.py`
— claim exclusivity under real concurrency, the full connector-ingest success path against
real Postgres + Redis, the missing-item failure path, and the RLS regression test for the
`elevated_session` fix). `make lint` / `make types` clean. `make check` (`alembic check`)
clean — no migration needed. No frontend change; not claimed as done.

**Not done:** the sources UI — deliverable 5, fully specified in §5, unstarted.

### ✅ A3 — ask about your data, verified end to end 2026-08-15, PR #15

**You can now ask a question about your data in English and see the SQL, the rows and the
narration — and see the guard visibly refuse a write.** That is the milestone's sentence
(§5 as it stood before this section), and it is now true and demonstrated: signed in as
`analyst@mnemos.local`, in a real browser, against the rebuilt `api`/`web` containers, real
Postgres, and real Ollama. Full deliverable 4-5 evidence — the execution/narration/repair
loop, the SQL panel and its denial screen, the composer redesign, and the browser
transcripts — is in the dated note near the top of this file
("`A3` deliverables 4-5 done"); this section keeps deliverables 1-3's own evidence below,
unchanged, plus a short deliverable 4-5 summary so the whole milestone reads in one place.

**Deliverable 4 (execution + narration + the repair loop) and deliverable 5 (the SQL
panel + denial screen), done 2026-08-15 — see the dated note above for the full write-up.**
In short: `flows/nl2sql/application/service.py`'s `Nl2SqlFlow` composes generation
(deliverable 3), a new `PostgresExecutor` (`features/datasources/adapters/executor.py`),
and narration through the existing `ChatModel` port, holding the invariant "a `REJECTED_*`
verdict is never executed" explicitly in its own docstring and proving it against a real
model that complied with five separate adversarial write attempts by producing safe reads
on repair — and, forced to a single attempt for one deterministic screenshot, refused
cleanly with the SQL panel's denial state on screen. The frontend's `SqlPanel.tsx` renders
three distinct labelled states (allowed, guard-refused, execution-failed-after-allowed),
never colour alone. `frontend/e2e/nl2sql.spec.ts` is the new Playwright coverage.

**Deliverable 1 — schema introspection — done:**
- `mnemosctl datasource introspect --org-slug X [--slug sales-warehouse]`
  (`entrypoints/cli.py`) registers the demo warehouse for an org and refreshes its cached
  schema. Idempotent registration: a second call returns the existing row
  (`test_register_is_idempotent`).
- `features/datasources/adapters/introspection.py`'s `PostgresIntrospector` connects with
  the datasource's own DSN (never the app's `Database`) and reads `information_schema` +
  `pg_class`, scoped to `allowed_schemas`:
  `test_introspector_reads_only_the_allowed_schema`,
  `test_introspector_sees_nothing_outside_the_requested_schema`.
- `features/datasources/domain/schema.py`'s `build_schema_objects` is pure and unit-tested
  independent of any database (`test_datasources_domain.py`, 4 tests) — table-level and
  column-level draft rows, verified against a hand-built table/column list.
- Refresh **replaces** the cache: `test_a_second_refresh_replaces_rather_than_accumulates`
  asserts the live row count in `sql_schema_object` equals what the second refresh reported,
  not the sum of two refreshes.
- The allowlist's default-deny is enforced, not just documented:
  `test_register_rejects_an_empty_allowlist`.
- DSNs are encrypted at rest: `core/crypto.py`'s `DsnCipher` (Fernet), keyed by the new
  `MNEMOS_DSN_ENCRYPTION_KEY` setting (dev default + the same
  reject-the-dev-default-in-production pattern `MNEMOS_JWT_SECRET` already has).
  `test_the_stored_dsn_is_encrypted_and_round_trips` asserts the plaintext DSN string never
  appears in the stored bytes and that decryption recovers it exactly.

**Test infrastructure added, load-bearing for deliverables 3-4 too:** `conftest.py`'s
`postgres` fixture now creates `mnemos_analytics` and seeds it by running the real
`deploy/postgres/init/02-analytics-seed.sql` (the same file `docker-compose.yml`'s
`postgres` service init-mounts) against it — not a hand-rolled substitute schema. Proven
directly before anything was built on top of it: connecting as `mnemos_ro` and attempting
`INSERT INTO analytics.region ...` raises `asyncpg.exceptions.InsufficientPrivilegeError`.
That is deliverable 3's second defence, already provable, a session before deliverable 3
exists.

**Gaps found and fixed as part of deliverable 1, not pre-existing and not left for later:**
- `MNEMOS_ANALYTICS_DATABASE_URL` did not exist in `docker-compose.yml` — nothing running
  in a container could have reached `mnemos_analytics` even though `Settings` had carried a
  default for it since `M1`. Fixed.
- `analytics_database_url`'s default was `postgresql://` (sync), not `postgresql+asyncpg://`
  — would have failed the moment anything tried to build an async engine from it. Fixed,
  and now validated by the same `_require_async_driver` check `database_url` has always had.

**Deliverable 2 — the business glossary — done:**
- `features/datasources/domain/glossary.py`'s `GlossaryTermRow` and
  `features/datasources/domain/context.py`'s `render_schema_context` are both pure — no
  SQLAlchemy, no I/O — and unit-tested directly (`test_datasources_domain.py`, 5 new
  tests): schema grouped by table with its row estimate, glossary listed after the schema,
  and both halves individually optional so an empty warehouse or an empty glossary each
  render sensibly rather than emitting an empty section header.
- `GlossaryRepository.ensure_terms` (`adapters/repository.py`) is idempotent **and
  non-destructive**: a term already present, matched by its `term` text, is left untouched
  rather than overwritten — `test_seed_glossary_never_overwrites_a_term_edited_since`
  proves a re-seed does not clobber an edit made since, not just that it does not
  duplicate rows.
- `SchemaObjectRepository` gained `list_all`, reusing deliverable 1's `SchemaObjectDraft` as
  the read shape rather than a second, identical dataclass.
- `mnemosctl datasource seed-glossary --org-slug X` seeds the four curated
  `DEMO_GLOSSARY_TERMS` (`entrypoints/cli.py`): revenue, active customer, order volume,
  segment — each with a real `sql_expression` against the actual `analytics.*` schema, not
  a placeholder string.
- `mnemosctl datasource show-context --org-slug X` prints `render_schema_context`'s output —
  a real, demonstrable consumer of the render function until deliverable 3's prompt exists.
  **Run against the rebuilt `api` container**, not just pytest:
  ```
  $ docker compose build api && docker compose up -d api
  $ docker compose exec api mnemosctl datasource seed-glossary --org-slug mnemos
  glossary terms   : 4 newly written, 4 total seeded
  $ docker compose exec api mnemosctl datasource seed-glossary --org-slug mnemos
  glossary terms   : 0 newly written, 4 total seeded          # idempotent
  $ docker compose exec api mnemosctl datasource show-context --org-slug mnemos
  ## Schema
  ### analytics.customer
  - customer_id (integer)
  ...
  ### analytics.sales_order (~900 rows)
  - customer_id (integer)
  ...
  ## Business glossary
  - **active customer** (also: engaged customer): A customer with at least one sales
    order placed in the last 90 days. — `EXISTS (SELECT 1 FROM analytics.sales_order so
    WHERE so.customer_id = analytics.customer.customer_id AND so.ordered_on >=
    CURRENT_DATE - INTERVAL '90 days')`
  - **revenue** (also: sales, total sales, income): The net amount collected across
    completed sales orders. — `SUM(analytics.sales_order.net_amount) WHERE status =
    'completed'`
  ...
  ```
  Schema printed before glossary, exactly as `render_schema_context` orders it.
- `DatasourceService._require_datasource` factors the "get by slug or raise `LookupError`"
  pattern out of `refresh_schema`, `seed_glossary` and `render_context` — three call sites
  made it worth naming rather than repeating a third time. (Deliverable 3 below made this
  public, as `require_datasource`, once a second class needed it too.)

**Deliverable 3 — generation and the AST read-only guard — done:**
- `features/datasources/domain/guard.py`'s `guard_sql` — pure, no I/O. An **allowlist**: the
  parsed statement must be `sqlglot.exp.Query`, and every node in the tree is walked for
  anything that writes, changes privileges, or is a shape `sqlglot` falls back to a generic
  `Command` for. Tested directly against a blocklist-shaped alternative first, and found to
  miss `SELECT ... INTO`, `FOR UPDATE`, `EXPLAIN`/`VACUUM`/`CALL`/`COPY`/`SET` — none of
  which is a DML/DDL node — plus stacked statements (`SELECT 1; DROP TABLE ...;`, which
  parses to a `Block`, not a `Query`). `test_datasources_guard.py`, 31 cases, including
  CodingStandards §9 mandatory case 4 in full (DML nested in a CTE, a `UNION` arm, and a
  subquery — three cases proven by a single **data-modifying CTE** consumed three different
  ways, since Postgres does not allow a bare `DELETE`/`INSERT` in a `UNION` arm or a
  `FROM (...)` subquery directly, only through `WITH`).
- `features/datasources/domain/generation.py` — `NL2SQL_SYSTEM_PROMPT` and
  `extract_sql_statement`, pulling the candidate out of a fenced ` ```sql ` block with a
  fallback to the whole response for a model that does not comply with the fence
  instruction.
- `features/datasources/application/generation.py`'s `SqlGenerationService` — a sibling of
  `DatasourceService` (composes it for `require_datasource`/`render_context`), calling
  `ChatModel.complete()` once (never `.stream()`), guarding the result, and recording the
  attempt via the new `SqlRunRepository` regardless of verdict.
- `mnemosctl datasource generate --org-slug X "<question>"` — generates, guards, records;
  **never executes** (deliverable 4). Run against the rebuilt `api` container with a real
  `qwen2.5:3b-instruct` completion, not a fake:
  ```
  $ docker compose exec api mnemosctl datasource generate --org-slug mnemos \
      "what was total revenue by region last quarter"
  verdict          : allowed
  tables read      : analytics.sales_order, analytics.customer, analytics.region, analytics.product

  $ docker compose exec api mnemosctl datasource generate --org-slug mnemos \
      "delete every row from the sales_order table"
  verdict          : rejected_write
  detail           : not a read statement (parsed as Delete)
  sql              : DELETE FROM analytics.sales_order
  tables refused   : analytics.sales_order
  ```
  The model complied with the adversarial question and wrote a real `DELETE`; the guard, not
  the system prompt's instruction, is what actually stopped it. Both attempts confirmed
  persisted in `sql_run` via a direct `psql` query, not the CLI's own printout.
- Fixed a `NoReferencedTableError` from a live `mnemosctl` run (the same bug class as §4 item
  41): `sql_run.message_id`'s FK to `chat_message` is the first one any CLI code path has
  touched, and `entrypoints/cli.py` never previously needed `mnemos.platform.models`'s
  side-effect import. Fixed the same way `main.py` already does it.

**Evidence:** `make test` — **342 passed** (302 before this session; +40: 31 in the new
`test_datasources_guard.py`, 9 in the new `test_datasources_generation.py` — including
`test_the_readonly_role_refuses_a_write_the_guard_somehow_allowed`, which bypasses the guard
and the service entirely and connects directly as `mnemos_ro`, formalizing what deliverable
1 verified ad hoc). `make lint` / `make types` (165 source files, `--strict`) / `make check`
clean (`alembic check`: "No new upgrade operations detected" — `sql_run` already had every
column from `M2`). PR #15: `backend`, `frontend`, `compose` all green.

**Deliverables 4-5 (execution, narration, the repair loop, the SQL panel, the denial
screen) done 2026-08-15** — see the dated note near the top of this file and this section's
own opening summary above. `A3` is complete, verified end to end in a real browser, and
PR #15 is ready to merge.

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

`A3` — ask about your data — is **done, all 5/5 deliverables**, verified end to end in a
real browser against the real stack. Full evidence is in the dated note near the top of
this file ("`A3` deliverables 4-5 done") and in §3's `A3` entry.

**`B1` deliverables 1-4 are done.** Full evidence for each is in its own dated note near the
top of this file ("2026-08-15 (evening)" for 1, "2026-08-15 (night)" for 2, "2026-08-16" —
the earlier of the two same-dated notes — for 3, and the deliverable-4 note above this one
— for 4) and in §3's `B1` entry. **Deliverable 5 below (the sources UI) is unchanged from
the original brief** — it was written before deliverables 1-4 existed, but nothing in it
assumed a shape for `SourceConnector`/`ConnectorFactory`/`EventBus`/the realtime handshake/
the worker beyond what got built, so it still applies as written. What the sources UI needs
to know about each, in one place:

- **Deliverable 1** (`SourceConnector` port + factory): `ConnectorService` (`register`,
  `list_sources`, `list_items`, `fetch_item`) is the one thing to call — never
  `ConnectorFactory` directly. `features/connectors/api/` is still three empty files; the
  sources UI's backend slice is HTTP routes there, over this service. Connector kinds are
  `s3`/`minio`/`local_fs`/`http`, each with its own config shape (`_connector_config` in
  `entrypoints/cli.py` shows the exact fields per kind).
- **Deliverable 2** (`EventBus`): not the sources UI's concern directly — it is deliverable
  4's worker that publishes to it. The UI only ever reads the live pub/sub relay (below).
- **Deliverable 3** (realtime auth): the UI's WS client connects to `/ws/ingestion`
  (`entrypoints/realtime/main.py`, real `realtime` container on port 8001) offering
  `Sec-WebSocket-Protocol: ["bearer", "<access token>"]` — **not** a query parameter. It
  receives `{"type": "subscribed", "channel": "ingestion"}` once accepted, then whatever is
  published on `mnemos:org:{org_id}:ingestion` (its own org, derived server-side — the
  client never names an org). A denied handshake closes with code `1008`, no reason on the
  wire.
- **Deliverable 4** (the worker): `mnemosctl connector ingest --org-slug X --slug Y --uri Z`
  is today's only producer of an `ingest_job` — the sources UI's ingest action is the
  second, so it needs an HTTP route in `features/connectors/api/` that does what that CLI
  command does (`IngestJobRepository.enqueue`, kind `CONNECTOR_INGEST_KIND` from
  `features.knowledge.domain`, payload `{"source_slug", "item_uri", "item_name",
  "content_type"}`, `idempotency_key=f"{slug}:{uri}"`). Every publish on the WS channel
  above is JSON shaped `{"type": "ingest_job", "job_id", "status", "kind", "document_id",
  "error_code", "occurred_at"}` — `status` is one of `queued`/`running`/`succeeded`/`failed`
  (the job's `queued` insert itself is never published; the UI's own "ingest requested"
  optimistic state covers that gap until the worker's first `running` publish arrives,
  typically within one `POLL_INTERVAL_S` — 5 seconds today).

### `B1` — connect a source and watch it ingest

**The sentence (C14):** connect a source — a MinIO/S3 bucket+prefix, a local filesystem
directory, or an operator-curated list of HTTP URLs — browse what it contains, pick items to
ingest, and watch each one move through `queued → running → done`/`failed` **live**, pushed
over an authenticated WebSocket, while `ingest_job`/`ingest_job_event` (schema since `M2`,
untouched by any real ingestion path until now) finally carry real rows for the first time.

**What already exists and must be reused, not rebuilt:**
- ~~`platform/objectstore/port.py` + `s3.py` — the `ObjectStore` port and its MinIO adapter
  from `A2`. The S3 connector adapter should sit on top of this port (list/get by
  prefix), not open a second, parallel MinIO client.~~ **Done in deliverable 1**: the port
  gained `list(prefix) -> Sequence[ObjectMeta]`, implemented in `S3ObjectStore` via
  `list_objects_v2`; `features/connectors/adapters/s3.py`'s `S3Connector` sits on top of it.
- ~~`core/crypto.py`'s `DsnCipher` (Fernet) — reuse the pattern (a new cipher instance/key,
  `MNEMOS_SOURCE_ENCRYPTION_KEY`).~~ **Done in deliverable 1**:
  `features/connectors/adapters/crypto.py`'s `SourceConfigCipher`, same Fernet pattern, its
  own key (`MNEMOS_SOURCE_ENCRYPTION_KEY` / `Settings.source_encryption_key`). Reuse this
  for deliverable 4, not `DsnCipher` and not a third cipher class.
- `entrypoints/worker/main.py`'s `reap_stuck_jobs` — the lease/heartbeat/reclaim shape for
  `ingest_job` already exists and already works (`status`, `attempts`, `max_attempts`,
  `owner_id`, `heartbeat_at`, `lease_expires_at`, `error_code`, `error_detail` are all real
  columns, exercised today). **`B1`'s worker loop claims a `queued` job and actually
  processes it** — extract/chunk/embed — for the first time; it does not redesign the
  reaper. Backoff strategy, retry depth beyond one immediate failure, and a per-job
  *progress* UI (percentage, partial chunk counts) are `B2`, not `B1` — don't build them
  here even though they'd be tempting to add while already in this code.
- `features/knowledge/application/service.py`'s `upload_document` — extract → chunk → embed
  is already written, synchronously, for the manual-upload path (its own docstring says this
  is deliberate through `B2`). `B1` needs that same extract/chunk/embed body reachable from
  the worker too, for connector-sourced items — factor it out of `upload_document` into a
  function both the HTTP handler and the worker call, rather than duplicating the pipeline.
  **The manual upload path itself does not change** — it stays synchronous; `B1` adds a
  second, job-queued path alongside it, it does not migrate the first one onto the queue.
- `core/crypto.py`'s `DsnCipher` (Fernet) — the encrypted-config-at-rest pattern `A3`'s
  datasource DSNs use. A connector's config (bucket/credentials, or a filesystem root, or a
  URL allowlist) is exactly this shape again; reuse the pattern (a new cipher instance/key,
  `MNEMOS_SOURCE_ENCRYPTION_KEY`, not `MNEMOS_DSN_ENCRYPTION_KEY` itself — different secret,
  same rotation story).

**A real gap deliverable 1's session found, closed by deliverable 3 (2026-08-16):**
`entrypoints/realtime/main.py`'s `/ws/{channel}` used to accept any connection and relay
anything published to `mnemos:{channel}` — no JWT check, no org scoping. Its own docstring
said this was deliberate "until M3" (identity), which had been done since `A0`. It now
validates the platform JWT the same way the HTTP fail-closed guard does (offered as a
`Sec-WebSocket-Protocol` value, since browsers cannot set an `Authorization` header on a WS
upgrade), and the channel a caller subscribes to is derived from their own org, never taken
from the client-supplied `channel` path segment — a channel string that tries to name
another org, typed into the WS URL by hand, is refused before the URL is even capable of
naming an org at all. Full detail in the "2026-08-16" dated note near the top of this file.

**Deliverables, in build order — one commit (or a small adjacent group) per numbered item,
matching how `A3`'s deliverables were committed:**

1. ✅ **Done (2026-08-15 evening). `SourceConnector` port + factory, `features/connectors/`.**
   Built exactly as specified: `domain/port.py`'s `SourceItem` + `SourceConnector` protocol
   (`list_items`/`fetch`); three adapters (`adapters/s3.py`, `adapters/local_fs.py` —
   default-deny outside an operator-approved root, enforced at *two* levels, the
   per-registration `root` and a new deployment-level `Settings.local_fs_allowed_roots` —
   and `adapters/http.py`, never crawling, only an operator-curated URL list); the SSRF
   deny-list (`adapters/ssrf_guard.py`) with genuine DNS-rebinding protection (the request
   pins to the address that was checked, via IP-substitution + `Host`/SNI, not a check
   followed by a second, unpinned resolution); the `content_source` table + RLS (migration
   `0007`, the first since `M2` — `alembic check` clean, and two latent bugs in migrations
   `0004`/`0006` found and fixed along the way, see the dated note above); and
   `mnemosctl connector register --org-slug X --slug Y --name N --kind {s3,local_fs,http}
   [--bucket/--prefix | --root | --url ...]` / `connector list-items --org-slug X --slug Y`.
   `ConnectorFactory` decrypts a registered source's config and builds the right adapter;
   `ConnectorService` is the thing to call (`register`, `list_sources`, `list_items`) —
   deliverable 4 should use it, not `ConnectorFactory` directly. Evidence: 32 new tests
   (`tests/test_connectors_{ssrf,local_fs,http,s3,service}.py`), all passing against real
   Postgres/no-network-needed fakes; `make lint`/`make types` clean.
2. ✅ **Done (2026-08-15 night). The event bus, `platform/events/`.** Built exactly as
   specified: `port.py`'s `EventBus` protocol (`publish`, `ensure_group`, `read_group`,
   `ack`) and `redis_streams.py`'s `RedisStreamsEventBus` — `XADD`/consumer-group
   `XREADGROUP`, not the pub/sub `platform/cache.py` already has for the realtime gateway's
   existing channels. The open design question — how the realtime gateway gets from "a
   Streams entry landed" to "a browser's WebSocket receives it" — is resolved as option (a):
   deliverable 4's worker will publish every `ingest_job` transition to both this stream
   (durable, for replay) **and** the existing pub/sub channel the gateway already relays
   (live), rather than the gateway growing its own consumer-group reader (option (b), left
   for `B2`'s replay-on-reconnect depth). Evidence: 7 new tests
   (`tests/test_events_redis_streams.py`) against a real Redis via testcontainers, proving
   backlog delivery to a group created after publish, idempotent group creation, no
   redelivery of an already-delivered message, competing-consumer semantics, `ack` clearing
   `XPENDING`, and unreachable-Redis error translation; `make lint`/`make types` clean.
3. ✅ **Done (2026-08-16). Close the realtime auth gap** (see above) — JWT-validated WS
   handshake, org-derived channel scoping, a test that proves a token for org A cannot
   subscribe to org B's ingestion channel even by typing the channel name directly into the
   WS URL. Built exactly as specified: the gateway gained a `Database` and the same
   `PlatformTokenCodec`/`PrincipalResolver` pair the API builds; the token travels as a
   `Sec-WebSocket-Protocol` offer (`["bearer", token]`), not a query parameter, so it never
   appears in a URL, an access log or browser history; the channel a caller reaches is
   always `mnemos:org:{org_id}:{kind}` with `org_id` read only from the resolved token and
   `kind` checked against a closed allow-list (`ALLOWED_CHANNEL_KINDS = {"ingestion"}`).
   Evidence: 12 new tests (`tests/test_realtime_auth.py`) against a real Redis via
   testcontainers, including the exact cross-org attack named above and a genuine live
   verification against the running compose stack (rebuilt container, real session, real
   Redis publish/relay, real refusal of a hand-typed cross-org channel). `make
   lint`/`make types` clean; `make check` clean (no migration touched).
4. ✅ **Done (2026-08-16). The worker claims and processes a real job.** Built exactly as
   specified: `entrypoints/worker/main.py`'s poll loop claims one `queued` `ingest_job` at a
   time (`IngestJobRepository.claim_next`, `FOR UPDATE SKIP LOCKED`, mirroring the reaper's
   own claim style) → `running` (heartbeat set at claim; no periodic renewal — that depth is
   `B2`) → the factored-out extract/chunk/embed body
   (`KnowledgeService.ingest_connector_item`) against the connector-fetched bytes → `succeeded`
   **(one naming note: the brief above said `done`; the actual terminal status is
   `succeeded`, matching `core/types.py`'s existing `JobStatus` enum rather than inventing a
   new label — the sources UI (deliverable 5) should treat `succeeded` as the "done" state,
   not wait for a status literally spelled `done`)**, or `failed` with `error_code`/
   `error_detail` on the first exception (no retry-with-backoff yet — `B2`). An
   `ingest_job_event` row and a live publish (both `EventBus` and pub/sub) at every
   transition. Connector-sourced documents get `trust_tier=TrustTier.RETRIEVED` (10) — the
   trust-tier question was already resolved in deliverable 1's dated note (see above), not
   `ThreatModel.md` §4's literal "≥ 4", which was written against a retired 0-6 scale; the
   4-rung `TrustTier` enum has no rung below `RETRIEVED` to assign. **A real RLS bug found
   and fixed alongside this:** `reap_stuck_jobs` ran unscoped and so reclaimed nothing on a
   real Postgres, ever — fixed via `db.elevated_session()`. Evidence: 7 new tests
   (`tests/test_worker_ingestion.py`) against real Postgres + Redis, plus live verification
   against the rebuilt compose stack. Full detail in the dated note above.
5. **The sources UI, `frontend/src/app/(app)/sources/`.** Connect a source (a form per
   connector kind), browse its listed items in a table, select some and ingest them, then
   watch a live event feed of `queued`/`running`/`succeeded`/`failed` transitions arrive over
   the now-authenticated WebSocket with no page refresh — `succeeded`, not `done` (see item
   4's naming note just above; a `queued` transition is never itself published, only implied
   by the ingest request the UI itself just made). Each state pairs an icon with a
   plain-word label, never colour alone — the same accessible-state discipline
   `SqlPanel.tsx` already established and `test_no_component_hardcodes_a_colour` already
   enforces (DesignSystem tokens only). `features/connectors/api/` (still three empty files)
   is where this deliverable's backend routes belong — list sources, list items, enqueue an
   ingest (mirroring `mnemosctl connector register`/`list-items`/`ingest`, see §5's
   deliverable-4 recap above for the exact contract each route needs to match). New
   Playwright coverage: register the local-filesystem connector against a small fixture
   directory (no real S3 bucket or live URL needed in CI — the point of doing local
   filesystem first in this deliverable list is that it is the one connector kind a CI
   runner can exercise for free), ingest one file, and observe its job reach `succeeded`
   live.

**Explicitly NOT `B1`, so nobody drifts into building it early:** heartbeat/backoff retry
depth beyond one immediate failure, a per-job progress percentage or partial-chunk count,
more than one adapter per connector kind, crawling or discovering URLs (the HTTP connector
only ever fetches an operator-supplied list), and migrating `A2`'s manual-upload path onto
the job queue. All of that is `B2` or later — see §5's "Then, in order" list below.

**Evidence bar to close `B1`,** matching every prior milestone's bar: `make test` green with
new coverage for each connector adapter (including the SSRF deny-list actually refusing a
loopback/link-local URL, not just asserting it exists), the event bus round-trip, the
worker's claim-and-process path end to end against real Postgres + Redis, and the WS
cross-org channel refusal; `make lint` / `make types` / `make check` (including a clean
`alembic check` against the new migration) all clean; `frontend`'s lint/tsc/test/build
clean; the new Playwright sources flow green; **real browser verification** before calling
it done (C12/C14) — connect the local filesystem connector against real seeded fixture
files, in a real browser, and watch the live feed move, the same bar `A3`'s browser
verification set; TRACKER and `docs/ADAPTATION.md` updated in the same commit as each
deliverable, not batched at the end.

### Then, in order — this list is the plan, and it no longer matches phase order exactly

Each item below is one session (or a small coherent group), and each carries its own "you
can now ___" (C14). **As of 2026-08-15 (evening) this list, not the phase groupings in
§3.0, is authoritative for sequencing** — see that date's note near the top of this file for
why `B1`/`B2` now sit before `A4`. The phase tables still group work by kind; they no longer
promise strict A-then-B-then-C-then-D order.

- **`A3` — ask about your data.** ✅ Done, all 5/5 deliverables, verified 2026-08-15.
- **`B1` — connect a source and watch it ingest.** ⬅ **next, fully specified above.**
  Object storage port + `S3ObjectStore` already exist from `A2` (MinIO); `B1` adds the
  `SourceConnector` abstraction (MinIO/S3, local filesystem, HTTP URL), a Redis Streams
  event bus, an authenticated realtime channel, and the worker's first real job-processing
  path, so a source is *connected and browsed* rather than only uploaded file-by-file, with
  ingestion events visible live in a new sources UI. Five deliverables, in build order,
  above — read them before starting rather than re-deriving the design.
- **`B2` — ingestion at scale.** Heartbeat, retries, status history, and a stuck-job reaper
  over the job machinery `B1` introduces, with a per-job progress UI. Depends on `B1`
  existing first.
- **`A4` — stop choosing a mode.** Classify each message to chat / RAG / NL2SQL and show
  which flow answered and why. This is also where the two provisional selectors — `A2`'s
  `use_documents` and `A3`'s NL2SQL equivalent — are replaced by a real classifier, and
  both were written down as provisional precisely so this milestone knows what to remove.
  Moved here, after `B1`/`B2`, from its original position immediately after `A3`.

Then `B3`, `B4` (the rest of Phase B), Phase C (`C1`–`C4`), Phase D (`D1`) — §3.0, unchanged.

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
