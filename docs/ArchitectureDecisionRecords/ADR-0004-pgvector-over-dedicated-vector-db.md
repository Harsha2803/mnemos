# ADR-0004 — pgvector over a dedicated vector database

**Status:** Accepted · **Date:** 2026-07-26

## Context

Vector search is on the critical path. The options are a dedicated engine (Qdrant,
Milvus, Weaviate) or pgvector inside the existing PostgreSQL instance.

The decisive requirement is unusual and worth stating first: **authorization must be
evaluated inside the index scan, not after ranking.** Post-filtering leaks the existence
of inaccessible documents through result-count side channels and destroys recall — if the
top-100 ANN neighbours are all inaccessible, post-filtering returns nothing while
thousands of accessible relevant documents exist.

## Decision

**pgvector with HNSW, ACL columns denormalized onto the embedding row, behind a
`VectorIndex` port.**

```sql
CREATE TABLE memory_embedding (
    ...,
    vec          halfvec(1536) NOT NULL,
    workspace_id uuid,                    -- denormalized
    sensitivity  sensitivity_level NOT NULL,   -- denormalized
    tags         text[] NOT NULL DEFAULT '{}' -- denormalized
);
CREATE INDEX ... USING hnsw (vec halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);
```

## Rationale

**1 — Filtering with full SQL expressiveness.** The authorization predicate is arbitrary:
org, workspace, sensitivity level, tag membership, and validity interval. Postgres
evaluates all of that natively alongside the ANN scan. Dedicated engines support payload
filtering, but with a restricted expression language that would force either
simplification of the policy model or a post-filter — and post-filtering is banned.

**2 — Transactional consistency with the claim.** An embedding and its memory commit
together. With a separate engine, the write path becomes a dual write with its own drift
problem ([ADR-0002](ADR-0002-postgres-as-system-of-record.md)) or an eventual-consistency
window on a security-relevant field. If `sensitivity` changes in Postgres but the vector
store's copy lags, the system serves unauthorized results for the duration of the lag.

**3 — Joins.** Retrieval needs the vector *and* the claim's bitemporal state and lineage.
Same database, one query. Separate engine: fetch IDs, round-trip to Postgres, hydrate —
extra latency and an N+1 risk on the hot path.

**4 — Zero operational and monetary cost.** No extra service, no extra memory footprint,
no extra backup and restore procedure. Under the zero-cost constraint
([ADR-0008](ADR-0008-local-first-inference.md)) this matters concretely, not abstractly.

**5 — Honest scale assessment.** pgvector HNSW handles low-millions of vectors per
instance with acceptable latency. This project's realistic corpus is orders of magnitude
below that. Choosing a distributed vector engine for a single-node personal project would
be resume-driven development, and a reviewer would read it as such.

## Handling the real weakness: filtered-ANN recall

HNSW traversal with a selective filter can exhaust its candidate list before finding
enough matching neighbours. This is a genuine problem, not hand-waved:

1. **pgvector iterative index scans** with a bounded `hnsw.max_scan_tuples`, so the scan
   continues until enough matching candidates are found or the ceiling is hit.
2. **Exact-scan fallback within the org partition** when the statistics catalog estimates
   selectivity below a configured threshold. The planner knows the selectivity because
   `operator_stats.selectivity` tracks it — the cost model earns its keep here.
3. **A recall regression test** ([M4-T12](../ImplementationPlan.md#m4--retrieval-fabric))
   asserting pushdown beats post-filtering with 90% of the corpus inaccessible. Written as
   an inequality so a future "optimization" back to post-filtering fails CI.

## Alternatives considered

**Qdrant.** Excellent engine, good payload filtering, strong performance. Rejected: dual
write for a security-relevant field, a second store to operate and back up, and no
transactional consistency with the claim. Would be the right choice at tens of millions of
vectors.

**Milvus / Weaviate.** Stronger at very large scale, correspondingly heavier operationally
(etcd, object storage, multiple components). Wildly disproportionate here.

**Postgres + a separate ANN service.** Worst of both — dual write *and* an extra service.

## Consequences

**Positive** — ACL pushdown with full SQL expressiveness; transactional consistency;
single-store joins; no additional infrastructure or cost; RLS applies to embeddings too.

**Negative** — vector search competes with OLTP for the same resources; index builds are
memory-hungry and lock-sensitive (`CREATE INDEX CONCURRENTLY` is mandatory); pgvector will
be outperformed by dedicated engines at large scale.

**Escape hatch, deliberately built in.** All access goes through the `VectorIndex` port.
Migrating to Qdrant is one adapter plus a backfill, with no consumer changes. That is the
whole point of the port, and it is what makes this decision low-risk rather than a bet.

**Storage choice:** `halfvec` rather than `vector` — half the index memory at negligible
recall cost, and it raises pgvector's HNSW dimension ceiling from 2000 to 4000, keeping
larger embedding models available without a schema migration.
