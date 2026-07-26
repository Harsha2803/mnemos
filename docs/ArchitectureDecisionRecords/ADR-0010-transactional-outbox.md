# ADR-0010 — Transactional outbox over dual writes

**Status:** Accepted · **Date:** 2026-07-26

## Context

A memory write must update PostgreSQL and publish an event that drives embedding,
indexing, and graph projection. Writing to the database and then publishing to RabbitMQ
are two operations with no shared transaction.

The failure window is small and therefore easy to dismiss — the process can die between
commit and publish. At any real volume, "small" means "several times a week", and each
occurrence is a claim that exists in Postgres but is permanently unsearchable, with
nothing recording that it happened.

## Decision

**Domain events are inserted into an `outbox` table inside the same transaction as the
state change. A leader-elected relay polls unpublished rows, publishes to RabbitMQ, and
marks them sent. Consumers are idempotent, keyed on `(event_id, consumer_group)`.**

```sql
CREATE TABLE outbox (
    id uuid PRIMARY KEY, org_id uuid NOT NULL,
    aggregate_type text NOT NULL, aggregate_id uuid NOT NULL,
    event_type text NOT NULL, event_version integer NOT NULL DEFAULT 1,
    payload jsonb NOT NULL, trace_id text,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz, attempts smallint NOT NULL DEFAULT 0
);
CREATE INDEX outbox_unpublished_idx ON outbox (occurred_at) WHERE published_at IS NULL;
```

## Rationale

**Atomicity without distributed transactions.** Either the claim and its event both
commit, or neither does. There is no window. This is the entire value of the pattern, and
it is achieved with an ordinary local transaction.

**RabbitMQ becoming unavailable stops being a data-loss event.** Writes continue to commit;
the outbox accumulates; the relay drains on recovery. The failure degrades from "silent
permanent data loss" to "temporary staleness with an SLI" (`outbox_lag_seconds`).

**Idempotency is mandatory, not optional.** At-least-once delivery means duplicates *will*
occur — the relay can publish and then die before marking sent. `processed_event` makes
consumers exactly-once in effect.

**Partial index keeps the poll cheap.** `WHERE published_at IS NULL` makes the relay's
query `O(unpublished)` rather than `O(all events ever)`. Without it, the relay slows
linearly with total history — a problem that appears months later and looks like a
mysterious throughput decay.

**Trace ID travels with the event**, so an async projection's spans join the originating
request's trace. Otherwise the causal chain breaks exactly where debugging is hardest.

## Alternatives considered

**Dual write with a try/except.** The common shortcut. Rejected: it fails in the window,
and the compensating logic can itself fail. It produces the exact silent drift this
decision exists to prevent, while appearing to handle the problem.

**Publish first, then write.** Worse — an event may describe a state change that never
committed, so consumers act on a fiction.

**Change Data Capture (Debezium on the WAL).** Genuinely superior: no polling, no relay,
lower latency, no application involvement. Rejected on operational cost — Kafka Connect
plus a Debezium deployment is disproportionate for a single-node zero-cost project. The
outbox schema is CDC-compatible, so this remains the upgrade path rather than a dead end.

**Listen/Notify instead of a polling relay.** Lower latency, no polling. Rejected as the
sole mechanism: `NOTIFY` is fire-and-forget and delivers nothing to a disconnected
listener, so a relay restart loses notifications. Viable as an *optimization on top of*
polling (notify to wake the poller early), which is a reasonable later refinement.

**Two-phase commit between Postgres and RabbitMQ.** Rejected: blocking coordinator failure
modes, poor tooling, significant latency cost, and it solves a problem the outbox already
solves more simply.

## Consequences

**Positive** — no lost events; broker outages are survivable without data loss; complete
audit of emitted events; trace continuity into async work; CDC upgrade path preserved.

**Negative** — publish latency includes the poll interval (default 200 ms), which is
acceptable for projections and would not be for a user-facing path; the outbox table grows
and needs a pruning job for published rows; the relay is a singleton requiring leader
election (Postgres advisory lock), so it is a component that can stall and must be
alerted on.

**Operational requirement:** `outbox_lag_seconds` p95 < 5 s is a declared SLI
([SystemDesign §11](../SystemDesign.md#11-observability-contract)). A stalled relay is
invisible without it — writes keep succeeding while the system quietly stops indexing.
