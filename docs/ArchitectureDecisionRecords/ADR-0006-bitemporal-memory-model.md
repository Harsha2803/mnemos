# ADR-0006 — Bitemporal memory with non-destructive supersession

**Status:** Accepted · **Date:** 2026-07-26

## Context

Memory systems typically store facts and update them in place. When a user's preferred
language changes from Java to Python, the row is updated. Three questions then become
unanswerable:

1. What did the system believe last March? (audit, debugging, incident reconstruction)
2. When did this belief change, and what caused it?
3. Was the March answer wrong given what was known then, or wrong given what is known now?

The third distinction is the one that matters when reviewing an agent's past behaviour.
An agent that answered correctly from what it knew is a different problem from an agent
that reasoned badly, and destructive updates make them indistinguishable.

## Decision

**Two independent time axes per claim, and updates that never overwrite.**

```
WORLD TIME  : valid_from  → valid_to      when the asserted fact holds
BELIEF TIME : recorded_at → retracted_at  when the system held this belief
```

An update inserts a new row, sets `retracted_at` on the prior row, and creates a
`SUPERSEDES` edge. Enforced by a partial exclusion constraint:

```sql
EXCLUDE USING gist (
    org_id WITH =, subject_id WITH =, predicate WITH =,
    scope_hash WITH =, valid_range WITH &&
) WHERE (retracted_at IS NULL AND tombstoned_at IS NULL
         AND kind IN ('semantic', 'profile', 'procedural'));
```

## Rationale

**Two axes answer four distinct questions**, and only two of them are reachable with one
axis:

| `as_of` (world) | `believed_at` (belief) | Question answered |
|---|---|---|
| now | now | What do we think is true now? |
| past | now | What do we now think was true then? |
| now | past | What did we then think is true now? |
| past | past | **What did we think then, about then?** ← the audit question |

The fourth row is what an incident review or a compliance audit actually asks, and it is
unreachable without both axes. Retrofitting the second axis onto a populated single-axis
schema is a migration nobody wants to attempt, which is why this is decided on day one.

**Non-destructive updates give three properties simultaneously:**
- *Auditability* — every belief change is a durable record with a cause.
- *Security* ([ThreatModel T2](../ThreatModel.md#t2--memory-poisoning)) — memory poisoning
  becomes visible in lineage rather than destructive. The original claim still exists.
- *Correction without loss* — a wrong claim is superseded, not erased, so the correction
  itself is auditable.

**Why the exclusion constraint is partial by kind — the most important line in the
schema.** Two `semantic` claims that "default region is EU" and "default region is US"
cannot both hold over overlapping world time; that is a contradiction the database should
refuse. But two `episodic` memories about the same subject at the same instant are
completely normal — a person can do two things at once. Applying the constraint to
episodic memory would be a modelling error that surfaces as spurious insert failures under
concurrent ingestion, and would likely be "fixed" by dropping the constraint entirely.

**Why arbitration happens inside the write transaction.** Determining that a new claim
supersedes an old one is a read-modify-write on a logical key. Doing it asynchronously
opens a window where two contradictory claims are simultaneously `asserted`, which the
retrieval path surfaces as a spurious conflict. The exclusion constraint is the backstop
that makes the invariant enforceable rather than merely intended.

## Alternatives considered

**Single time axis (`created_at`, `updated_at`).** Simplest. Rejected: cannot answer the
audit question, and cannot distinguish "this became false" from "we learned it was always
false."

**Event sourcing (append-only events, derive state).** Full history, natural fit. Rejected:
every read becomes a fold over an event stream, requiring snapshots and projections for
acceptable retrieval latency. Bitemporal tables give the same auditability with direct
indexed reads. The outbox already provides an event stream where events are genuinely
needed.

**Soft delete (`is_deleted`).** Rejected: it records *that* something was removed but not
what replaced it, when the belief actually held, or why. It is the appearance of history
without its substance.

**Application-enforced overlap prevention.** Rejected on principle. An invariant enforced
only in application code is violated the first time a background job, a migration, or a
second code path writes without going through it. `EXCLUDE USING gist` is enforced by the
database for every writer.

## Consequences

**Positive** — full audit trail; the fourth-quadrant question is answerable; poisoning is
visible and reversible; corrections preserve history; NL2SQL schema drift inherits
temporal versioning for free ([ADR-0011](ADR-0011-three-flows-as-kernel-consumers.md)).

**Negative** — the table grows without bound and retracted rows eventually dominate, so
**every hot-path index must be partial on `retracted_at IS NULL`**; queries need two time
parameters, which is a real conceptual burden on API consumers; arbitration inside the
write transaction adds latency to writes.

**Known PostgreSQL limitation, recorded so it is not lost:** exclusion constraints are not
supported on partitioned tables. When `memory` is hash-partitioned by `org_id`, the
constraint must be created per partition. Because `org_id` is both a partition key and a
leading constraint column, per-partition constraints are collectively equivalent to the
global one.

**Mitigation for API burden:** both time parameters default to `now`, so the common case
is unaffected and the complexity is opt-in.
