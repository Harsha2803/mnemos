# ADR-0007 — One `memory` table with a `kind` discriminator, not eight tables

**Status:** Accepted · **Date:** 2026-07-26

## Context

The platform defines eight memory kinds: `working`, `conversation`, `episodic`,
`semantic`, `procedural`, `profile`, `reflection`, `workspace`. Each has a somewhat
different payload shape. The classic modelling choice applies: table-per-type,
single-table with a discriminator, or class-table inheritance.

## Decision

**One `memory` table with a `kind` enum and a per-kind typed `jsonb` payload, validated
by a Pydantic model at the application boundary.**

```sql
CREATE TABLE memory (
    id uuid PRIMARY KEY,
    kind memory_kind NOT NULL,
    subject_id uuid NOT NULL,
    predicate text NOT NULL,
    object_text text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,  -- kind-specific
    ...
);
```

## Rationale

**Cross-kind retrieval is the common case, not the exception.** A context compilation
asks for "the most relevant memories about this subject" across episodic, semantic, and
profile kinds simultaneously. With eight tables that is an eight-way `UNION ALL` with
per-branch ranking, executed on the hot path, for every request. That is a self-inflicted
wound, and it is not recoverable later without a schema rewrite.

**The kinds share ~90% of their structure.** Subject, predicate, scope, bitemporal
validity, trust tier, confidence, importance, strength, access counters, content hash,
lineage — all identical across kinds. What differs is a small payload. Table-per-type
would duplicate thirty columns eight times and force every lifecycle change (decay,
reinforcement, compaction) to be written eight times, with the inevitable drift.

**Lineage edges are cross-kind by nature.** A `reflection` derives from `episodic`
memories; a `semantic` claim supersedes a `profile` claim. With eight tables, `memory_edge`
cannot have foreign keys at all — it needs a polymorphic `(kind, id)` reference with no
referential integrity. One table means real foreign keys.

**Constraints apply uniformly.** The bitemporal exclusion constraint
([ADR-0006](ADR-0006-bitemporal-memory-model.md)) is defined once with a `kind IN (...)`
predicate, rather than eight times with subtle divergence.

## The cost, stated honestly

`jsonb` payloads are not validated by the database. A malformed payload is possible if
something writes outside the application layer.

**Mitigations:**
- A discriminated-union Pydantic model per kind; `WriteClaim` is the only write path.
- A `CHECK` constraint asserting `jsonb_typeof(payload) = 'object'` as a floor.
- Integration tests asserting that each kind round-trips through its typed model.

This is a real trade. Database-enforced payload validation is genuinely better than
application-enforced. It is accepted because the alternative's cost — an eight-way union
on every retrieval — falls on the critical path of the system's core operation, while
this cost falls on a single, well-tested write path.

## Alternatives considered

**Table per kind.** Strong typing per payload, smaller tables. Rejected: eight-way union
on the hot path, thirty duplicated columns, polymorphic lineage without referential
integrity, eight copies of every lifecycle job.

**Class-table inheritance (shared base + per-kind detail).** Preserves typing and avoids
duplication. Rejected: every read becomes a join, and cross-kind retrieval still requires
either a union of the detail tables or a base-only query that cannot filter on
kind-specific fields. Worst of both.

**PostgreSQL table inheritance.** Rejected: constraints and indexes do not inherit
reliably, and it interacts badly with partitioning — which is on the roadmap.

**Separate physical columns for every kind's fields, mostly NULL.** Rejected: a wide,
sparse table where the meaning of each column depends on `kind`, with no enforcement of
which combinations are valid.

## Consequences

**Positive** — single-scan cross-kind retrieval; one set of constraints, indexes, and
lifecycle jobs; real foreign keys on lineage; new kinds are an enum value plus a payload
model, not a migration plus eight code changes.

**Negative** — payload shape is not database-enforced; the table is large and hot, so
index discipline (partial indexes on asserted rows) is mandatory rather than optional; a
`kind`-specific query cannot use a kind-specific index unless one is created partially on
that kind.

**Consequence accepted with a plan:** because the table is hot, partitioning by `org_id`
is the designated scaling step, and the design already accounts for the exclusion-constraint
limitation that comes with it.
