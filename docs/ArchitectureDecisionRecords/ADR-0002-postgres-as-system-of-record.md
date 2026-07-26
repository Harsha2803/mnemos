# ADR-0002 — PostgreSQL is the system of record; other stores are rebuildable projections

**Status:** Accepted · **Date:** 2026-07-26

## Context

The platform spans four stores: PostgreSQL (relational + vector), Neo4j (graph), Redis
(cache, locks, working memory), and an object store. A memory write must eventually be
visible in all of them.

The naive approach — write to each store in sequence — creates a distributed transaction
problem. Partial failure leaves stores permanently inconsistent with no principled
recovery, and the inconsistency is usually discovered months later as "the graph is
missing some nodes."

## Decision

**PostgreSQL is authoritative. Neo4j, the vector index, and all read models are
projections derived from the Postgres claim log and the event stream. Any projection can
be dropped and rebuilt.**

Writes commit to Postgres and to an `outbox` table in the *same transaction*. A relay
publishes committed events to RabbitMQ; idempotent consumers build the projections.

## Rationale

This converts a distributed-transaction problem into a local-transaction problem plus an
eventually-consistent fan-out — a trade with well-understood mechanics and a clear
recovery story.

**Disaster recovery becomes a sentence:** restore Postgres, replay projections. No
cross-store reconciliation, no "which store is right?" investigation. Compare that to the
alternative, where determining the correct state after a partial failure requires
manual forensics across four systems.

**It also removes an entire class of authorization bug.** If Neo4j were authoritative for
some data, tenant isolation would need a second correct implementation in a store that
(in Community Edition) has no row-level security. Making the graph a projection means
Postgres RLS remains the single enforcement point for the data that matters.

Cost: reads from projections are eventually consistent (seconds). This is documented as
an explicit API guarantee (`indexing.status` on write responses) rather than left as a
surprise for the first developer who writes then immediately searches.

## Alternatives considered

**Two-phase commit / XA across stores.** Correct in theory. In practice: no viable XA
support across pgvector, Neo4j, and Redis; blocking coordinator failure modes; severe
latency cost. Rejected.

**Dual writes with compensating transactions.** The common shortcut. It fails in the
window between the two writes — the process can die there, and the compensation logic
itself can fail. Produces exactly the silent drift this decision exists to prevent.

**Change Data Capture (Debezium on the WAL).** Genuinely good, and removes the relay's
polling. Rejected for this project on operational cost: Kafka Connect plus a Debezium
deployment is more infrastructure than a single-node zero-cost project can justify. The
outbox achieves the same delivery guarantee with a polling loop. If this ever needed real
scale, CDC would be the upgrade path, and the outbox schema is compatible with it.

**Neo4j authoritative for graph data.** Rejected: no RLS in Community Edition, a second
tenant-isolation implementation to get right, and no clean recovery story.

## Consequences

**Positive** — no distributed transactions; no lost events (outbox is transactional);
trivial DR; single point of tenant-isolation enforcement; projections can be redesigned
by rebuilding rather than migrating.

**Negative** — eventual consistency on retrieval (seconds); an outbox relay to operate,
with `outbox_lag_seconds` as an SLI; rebuild time grows with history, so the rebuild
script must be batched and resumable from the start.

**Operational requirement:** `scripts/rebuild_projections.py` ([M7-T6](../ImplementationPlan.md#m7--knowledge-graph))
is not optional tooling. It is the mechanism that makes this decision safe, and it is
verified by a test that drops the entire graph and asserts an identical rebuild.
