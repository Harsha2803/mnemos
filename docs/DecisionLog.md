# Decision Log

A running record of decisions, including the ones that turned out to be wrong. An
architecture document shows the destination; this shows the route, which is usually more
instructive.

**Convention:** significant, hard-to-reverse decisions get a full ADR. Everything else is
a row here. A decision that is later reversed is **struck through and annotated**, never
deleted — the reversal is the most informative part.

---

## Architecture Decision Records

| ADR | Decision | Status |
|---|---|---|
| [0001](ArchitectureDecisionRecords/ADR-0001-context-as-compiled-artifact.md) | Context is a compiled artifact, not a concatenated string | Accepted |
| [0002](ArchitectureDecisionRecords/ADR-0002-postgres-as-system-of-record.md) | PostgreSQL is the system of record; all other stores are rebuildable projections | Accepted |
| [0003](ArchitectureDecisionRecords/ADR-0003-feature-first-clean-architecture.md) | Feature-first layout with clean-architecture layers, enforced by import-linter | Accepted |
| [0004](ArchitectureDecisionRecords/ADR-0004-pgvector-over-dedicated-vector-db.md) | pgvector over a dedicated vector database | Accepted |
| [0005](ArchitectureDecisionRecords/ADR-0005-token-budget-allocation.md) | Lagrangian-relaxed greedy allocator over exact ILP | Accepted |
| [0006](ArchitectureDecisionRecords/ADR-0006-bitemporal-memory-model.md) | Bitemporal memory with non-destructive supersession | Accepted |
| [0007](ArchitectureDecisionRecords/ADR-0007-single-memory-table-discriminator.md) | One `memory` table with a `kind` discriminator, not eight tables | Accepted |
| [0008](ArchitectureDecisionRecords/ADR-0008-local-first-inference.md) | Local-first inference; zero paid dependencies in the default path | Accepted |
| [0009](ArchitectureDecisionRecords/ADR-0009-trust-tiers-and-tool-authorization.md) | Monotone trust tiers with re-authorization at the tool boundary | Accepted |
| [0010](ArchitectureDecisionRecords/ADR-0010-transactional-outbox.md) | Transactional outbox over dual writes | Accepted |
| [0011](ArchitectureDecisionRecords/ADR-0011-three-flows-as-kernel-consumers.md) | Three flows as consumers of one kernel, not three pipelines | Accepted |
| [0012](ArchitectureDecisionRecords/ADR-0012-licensing-and-openness.md) | Apache 2.0 | Accepted |

---

## Decision log

### 2026-07-26 — Project scope refined from the original brief

**Context.** The initial brief specified eleven modules (auth, memory, context,
lifecycle, hybrid retrieval, knowledge graph, agent runtime, tool runtime, LLM gateway,
observability, dashboard) all at production quality.

**Decision.** Build all of it, but concentrate the novelty budget in three pillars —
the context compiler, bitemporal memory, and governed retrieval — and treat auth,
gateway, and observability as competent supporting infrastructure rather than
differentiators.

**Rationale.** Each of the eleven modules is a funded company's entire product. Spread
evenly, the result is eleven shallow implementations, which reads as inexperience rather
than ambition. Four of the eleven also repeat work already done professionally (auth
framework, MCP gateway, LLM gateway, cloud abstractions) and therefore demonstrate
nothing new.

---

### 2026-07-26 — ~~NL2SQL excluded as a non-goal~~ **REVERSED same day**

**Original decision.** Exclude NL2SQL, on the grounds that it repeats prior professional
work.

**Reversal.** NL2SQL is included as Flow B, reframed as a *consumer of the context
kernel* rather than a bespoke pipeline.

**Why the reversal is right, and why the original reasoning was incomplete.** The
original decision optimized for "don't repeat yourself" and missed the stronger argument:
an abstraction with one consumer is speculation. Three heterogeneous consumers —
retrieving chunks, schemas, and tool catalogs respectively — are what make the kernel
*proven* rather than merely asserted. The differentiation is not in avoiding NL2SQL; it
is in the fact that the stages previously hand-wired as a fixed 7-step pipeline are now
operators the compiler plans over. That is a visible, explainable step forward from the
prior work rather than a repetition of it.

**Additional benefit not initially seen.** Storing warehouse schema as memory claims
means schema drift inherits bitemporal versioning for free — "what did this schema look
like in March?" needs no new code. That reuse is itself evidence the kernel abstraction
is correct.

---

### 2026-07-26 — Zero-cost constraint adopted; latency targets corrected

**Context.** The project must run with no paid API, using local models, while remaining
pluggable to hosted providers.

**Decision.** Local-first inference ([ADR-0008](ArchitectureDecisionRecords/ADR-0008-local-first-inference.md)).
Cost denominated in provider-agnostic `compute_units`.

**Correction issued.** Latency targets originally written into
[SystemDesign §2](SystemDesign.md) assumed hosted inference and were wrong by more than
an order of magnitude for local CPU execution. They have been replaced with two-tier
(`cpu-standard`, `gpu-8gb`) measured-intent targets. Leaving optimistic numbers in a
design document is worse than having none, because they become the baseline nobody
questions.

**Consequences that improved the design rather than degrading it.**
- Intent classification defaults to an embedding-centroid classifier (~10 ms) instead of
  an LLM call (~3.5 s on CPU). Cheaper *and* more deterministic.
- The rerank gate stopped being a micro-optimization and became the difference between a
  125 ms and a 550 ms response.
- The budget allocator became genuinely load-bearing. On CPU the binding constraint is
  latency, not tokens — which is the more interesting optimization problem and a better
  demonstration of why a cost-based optimizer is warranted.

---

### 2026-07-26 — `mnemos-tools` is a separate service, not a module

**Decision.** MCP tool execution runs in its own process with its own credential store
and network boundary.

**Rationale.** It is the only component that executes attacker-influenceable code paths
against third-party systems holding real user OAuth tokens. Co-locating it with the API
would place a compromised tool adapter in the same address space as the policy engine.
The operational cost — one more container, one more deployment unit — is small; the
blast-radius reduction is not.

---

### 2026-07-26 — Repo-local git identity set to a personal account

**Decision.** `user.email` and `user.name` are set repo-locally to the personal account,
leaving the global work identity untouched.

**Rationale.** The global git config on this machine is a work identity
(`@jktech.com`). Personal open-source commits authored under an employer email create
avoidable ambiguity about IP ownership, and the attribution is effectively permanent once
pushed.

---

### 2026-07-26 — Private repository until v0.2

**Decision.** Private now; public at v0.2 (kernel + one working flow).

**Rationale.** A public repository whose first forty commits are documentation tells a
weaker story than one that opens with a working, runnable system. The decision is cheap
to reverse in one direction (private → public) and impossible in the other.

---

## Reversal record

*Decisions overturned by evidence. Kept permanently.*

| Date | Original | Reversed to | Trigger |
|---|---|---|---|
| 2026-07-26 | NL2SQL excluded as a non-goal | Included as Flow B, kernel-consuming | Product direction + a better architectural argument |
| 2026-07-26 | Hosted-inference latency targets | Two-tier local-inference targets | Zero-cost constraint made the originals wrong |
