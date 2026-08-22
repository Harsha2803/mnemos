# Demo — a scripted walkthrough

**Purpose.** One deterministic path through Mnemos's strongest journeys, suitable for a
screen recording or a live interview. Every step below is either a command committed in
this repository or a click in the running app — nothing here is a hand-edited database row
or an external account. Total run time is roughly 8-10 minutes read at a normal pace.

This is a script for a *person*, not a test. `frontend/e2e/*.spec.ts` (run via
`npx playwright test`) proves the same journeys mechanically on every change; this document
is what you say and click while a reviewer watches.

---

## 0. One-time setup

From a clean stack (see the root [`README.md`](../README.md) Quickstart if you have not
started it yet):

```bash
docker compose up -d
make wait                      # blocks until every dependency is ready
make demo-seed                 # idempotent — safe to re-run before every recording
```

`make demo-seed` does three things, none of them visible in the UI on their own, all of
them prerequisites for the walkthrough below:

1. Registers and introspects the seeded `analytics.*` warehouse (`sales-warehouse`) so
   NL2SQL has a schema to generate against.
2. Seeds its business glossary (4 terms — `revenue`, `region`, `active customer`, `order`).
3. Registers the `e2e-fixtures/sources/handbook.txt` fixture as a `local_fs` connector
   (slug `demo-fixtures`) so Sources has something to browse and ingest live in step 2
   below, rather than requiring a file to be found and dragged in on camera.

Sign-in credentials throughout: **workspace `mnemos`, email `analyst@mnemos.local`,
password `analyst`** — a seeded Keycloak user, not a real account. `admin@mnemos.local`
also works (password `admin`) if a step needs the `admin` role; the walkthrough below does
not.

---

## 1. Sign in and orient (30s)

Open `http://localhost:3000`, enter workspace `mnemos`, click **Continue with Keycloak**,
sign in as `analyst@mnemos.local` / `analyst`. Land on the app shell: sidebar (conversations,
Knowledge, Sources, Memory, Tools), the composer, and the inspector on the right.

**Say:** "This is a real OIDC round trip against Keycloak, not a mocked login — platform JWT
with refresh rotation underneath, and every route is authenticated by default."

---

## 2. Documents — connect a source, ingest it live, ask about it (2 min)

1. Open **Sources**. `demo-fixtures` is already registered (from `make demo-seed`) — click
   it, see `handbook.txt` listed, select it, click **Ingest 1**.
2. Watch the activity feed move `Queued → Running → Succeeded` **live**, no page reload —
   that is the worker claiming the job and the authenticated WebSocket gateway relaying its
   progress.
3. Open **Chat → New chat**. Ask:

   > According to the uploaded handbook, how many leave days carry over?

4. The router labels the answer **Documents** with its reason. The answer cites the source;
   click the citation marker to open the inspector on the exact passage (`five working days`,
   with a character offset into the original file).

**Say:** "Retrieval is hybrid — vector plus trigram, fused, deduplicated — and the
authorization predicate is inside the scan itself, not a filter applied after. A document
this user cannot see is never scored, not merely hidden from the results."

---

## 3. Database — ask in English, see the guard (2 min)

Still in the same or a new chat session, ask:

> What was total revenue by region?

The router labels this **Data**. The SQL panel shows the generated `SELECT`, the result
grid, and a narrated answer. Point at the panel: this is the exact statement that ran, not a
paraphrase.

Now demonstrate the guard with a deliberately adversarial question:

> Delete every row from the sales_order table.

The screen shows one of two legitimate outcomes — a refusal naming the read-only guard, or
(if the repair loop talked the model into a safe read on the second attempt) an allowed
`SELECT` with results. **Either is correct**; what must never appear is a write having run.

**Say:** "Two independent defences: an AST allow-list rejects anything that is not a read
before it ever reaches the database, and even an allowed statement executes as `mnemos_ro`,
a role that is physically incapable of writing. A parser bug in the first defence still
meets the second."

---

## 4. Tools — register, approve, and run one MCP call (2 min)

1. Open **Tools**. Register the bundled server: slug `demo`, name `Demo MCP`, endpoint
   `http://demo-mcp:8100/mcp`. Click **Discover** — the `echo` tool appears, labelled
   **Read-only**.
2. Click **Grant to me**, type a short message, **Propose call**.
3. The call appears under **Proposed call**, waiting for approval. Click **Approve and run**
   — the invocation succeeds and its result (your message, echoed back) appears in history.

**Say:** "Every invocation rechecks the live role, the personal grant, and the trust tier
that motivated the call — at dispatch time, not just when the grant was issued. Content
retrieved from a document can never motivate a user-tier tool on its own; the denial screen
names the offending source."

---

## 5. The Bundle inspector — open the compiled context itself (2 min)

Go back to the **Documents** or **Data** answer from steps 2-3, click **Inspect answer →
Bundle**. Walk through, in order:

- **Hard token budget** — exact tokens consumed against the configured budget (never over;
  it is a database `CHECK` constraint, not a convention).
- **Admitted / Excluded** counts, each candidate with its operator, score, trust tier, and
  — for an exclusion — the specific reason it lost (budget, ACL, superseded, duplicate,
  conflict).
- **Compiled prompt** — the literal text handed to the model, in the same order the sections
  were assembled.

**Say:** "This is not a log of what happened — it is the actual persisted artifact the
answer was generated from, replayed from storage. Every supported answer flow attaches one
of these to its message. That's the project's central technical claim: the prompt is a
compiled, budgeted, inspectable artifact, not a concatenated string — and the numbers behind
it are in the README, reproduced by `make bench` on the same Postgres this stack runs."

---

## Optional: Memory — supersession and retraction (2 min, if time allows)

Open **Memory**. Create a claim (subject reference `employee:demo`, name `Demo Employee`,
predicate `home_hub`, claim `London`). Click **Supersede**, replace it with `Berlin` — the
old fact is not overwritten, its belief interval closes and a lineage edge is written in the
same transaction; both `London` and `Berlin` remain visible with their validity ranges. Ask
a chat question referencing the demo employee and open its Bundle to see the current fact
admitted and the superseded one excluded with a named reason.

---

## Resetting for a re-recording

The whole state above is reproducible from nothing but committed fixtures and seeded
Keycloak users — never hand-edit a row to reset it:

```bash
docker compose down -v      # drops all volumes — a genuinely empty next start
docker compose up -d && make wait && make demo-seed
```

Or, to keep infrastructure state (Postgres/Redis/MinIO/Ollama already primed) and only
clear conversations/documents/memory created *during* a take, sign out and use a second
seeded user (`user@mnemos.local` / `user`) for the next run instead of tearing anything down.
