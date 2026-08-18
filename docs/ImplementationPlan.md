# Implementation Plan

**Last revised:** 2026-08-18

This is the committed implementation plan for turning Mnemos into a focused, resume-ready
portfolio project. Live status and the complete brief for the next milestone remain in
[`TRACKER.md`](../TRACKER.md); architecture and the milestone ledger remain in
[`ADAPTATION.md`](ADAPTATION.md).

The plan intentionally optimizes for evidence of engineering depth, not feature count.
Completed capabilities stay supported and tested. Only two milestones remain committed:
a reduced `D1`; `B3` is complete on PR #23 and `C4` on PR #24.

## 1. Current baseline

The repository already demonstrates:

- multi-tenant OIDC authentication, platform JWT rotation, forced Postgres RLS, and CI;
- streamed local-model chat with automatic chat/RAG/NL2SQL routing;
- document ingestion, pgvector retrieval with authorization inside the scan, and citations;
- guarded NL2SQL with both an AST allowlist and a separate read-only database role;
- connector ingestion with Redis Streams, leases, heartbeats, retry/backoff, progress, and
  stuck-job surfacing; and
- one self-hosted MCP call with per-user encrypted credentials, live-role/trust checks,
  durable approval, invocation history, and a Tool console.

These are finished product capabilities, not prerequisites to rebuild.

## 2. Committed finish line

```text
C4 — governed context and bitemporal memory
  ↓
D1 — portfolio release and measured proof
```

### B3 — register and safely call one MCP tool ✅

**Portfolio signal:** modern tool use implemented with explicit security boundaries rather
than an unconstrained agent loop.

1. Reconcile domain records, ports, and org-scoped repositories with the existing MCP tables;
   keep credentials encrypted and isolated per user.
2. Implement one free, self-hosted streamable-HTTP MCP transport with discovery, endpoint
   enforcement, timeouts, response caps, and JSON-Schema argument validation.
3. Re-authorize at invocation time using live roles and the motivating trust tier; persist
   every proposal, approval, denial, result, and stable public failure reason.
4. Extend the existing routed chat for one tool call and add the authenticated Tool console
   for server registration, discovery, grants, approvals, and invocation history.
5. Verify policy, RLS, credential isolation, durable approval, trust-tier denial, and the
   complete browser flow against a deterministic local MCP fixture.

**Exit:** a user can register the local server, discover a tool, request one call, approve
it, and inspect the result; a retrieved-source-motivated call is denied with that source
named on screen. Verified 2026-08-18 against rebuilt Compose and Chromium; PR #23.

### C4 — build the governed context layer

**Portfolio signal:** Mnemos's differentiator—context is compiled, budgeted, inspectable,
and historically correct rather than concatenated ad hoc.

1. Port bitemporal memory and supersession from the quarantined v0.1 kernel to Postgres,
   preserving belief time, validity time, lineage, and database-enforced invariants.
2. Port the budgeted context compiler behind current ports, including calibrated utility,
   trust fences, conflict handling, exclusions, and the hard token-budget invariant.
3. Persist compiled bundles and `EXPLAIN` data so every admitted and excluded item has a
   reason, cost, provenance, and trust tier.
4. Replace the citation-only inspector state with a context-bundle UI that shows admissions,
   exclusions, conflicts, lineage, and token spend against budget.
5. Re-run the benchmark on Postgres, commit its machine-readable results, and replace every
   SQLite-labelled headline number in the README with reproducible measurements.

**Exit:** a user can open an answer and inspect exactly what context entered it, what was
excluded and why, and how the token budget was spent. Verified 2026-08-18 against migrated
Postgres, rebuilt Compose, Chromium, and the unchanged benchmark; PR #24.

### D1 — ship the portfolio release

**Portfolio signal:** a reviewer can run, verify, and understand the project without help
from its author.

1. Prove a clean-clone, one-command Compose startup path and make dependency failures
   actionable; do not add Kubernetes, paid hosting, or deployment abstractions.
2. Add Playwright coverage for the critical portfolio journeys: authentication, routed chat,
   RAG/citations, guarded NL2SQL, connectors/jobs, MCP approval/denial, and context inspection.
3. Create a deterministic demo dataset and short scripted walkthrough suitable for a screen
   recording and interviews.
4. Rewrite the README around verified capabilities, architecture decisions, benchmark data,
   security controls, exact reproduction commands, and honest limitations.

Realtime presence, nginx, and cosmetic breadth are included only if a measured release or
demo problem requires them. They are no longer independent completion requirements.

**Exit:** a reviewer can clone the repository, start it without an API key, follow one
documented walkthrough, and reproduce every material claim shown in the README.

## 3. Deliberately deferred

These are valid future extensions, but they are not part of the committed portfolio finish:

| ID | Deferred capability | Why it is not required now |
|---|---|---|
| `B4` | Multi-step agent plans, loops, checkpoints, recovery, and replay | Large reliability surface; B3 already demonstrates tool use and approval safety clearly. |
| `C1` | API keys, full permission matrix, tag-scoped ACL UI | Existing OIDC, live roles, forced RLS, and scan-time authorization already demonstrate the core security depth. |
| `C2` | Versioned prompt manager and cost dashboard | Useful operations breadth, but weaker resume signal than MCP safety or governed context. |
| `C3` | Folders, bookmarks, feedback, history search, expanded audit UI | Conventional product CRUD with limited differentiation. |

Deferred means **not promised**, not partially implemented. Existing schema columns or design
documents may preserve extension seams, but no agent should start these IDs unless the project
owner explicitly reopens scope after `D1`.

## 4. Delivery rules

- Finish reduced `D1`; `C4` is complete and its security/budget invariants remain mandatory.
- Keep the default path free and self-hosted; Ollama remains the model path.
- Preserve existing security invariants and do not weaken tests to shorten delivery.
- Every backend capability ships with its usable frontend slice.
- Prefer cutting optional surface area to cutting typing, tests, error handling, or evidence.
- End each milestone with full verification, synchronized planning docs and handoff, a green
  PR, merge to `main`, and a clean tracked worktree.
