# ADR-0011 — Three flows as consumers of one kernel, not three pipelines

**Status:** Accepted · **Date:** 2026-07-26 · **Supersedes:** the initial "NL2SQL is a
non-goal" position, reversed the same day — see [DecisionLog](../DecisionLog.md).

## Context

The platform must deliver three capabilities: RAG over unstructured PDFs, NL2SQL over
structured data, and an agent runtime using MCP tools.

The default way to build this is three pipelines side by side, each with its own retrieval
logic, its own ranking, its own prompt assembly. It works, it ships faster, and it is what
most systems do.

An earlier decision excluded NL2SQL entirely on the grounds that it repeated prior
professional work. That reasoning was incomplete and was reversed.

## Decision

**One context kernel; three flows that consume it. No flow contains retrieval logic.**

```
flows/rag      ──┐
flows/nl2sql   ──┼──▶  features/context (compiler)  ──▶  memory · retrieval · gateway
flows/agent    ──┘
```

Each flow owns only what is genuinely specific to it:

| Flow | Owns | Consumes from the kernel |
|---|---|---|
| RAG | PDF extraction, chunking, citation rendering | All retrieval, ranking, compression, assembly |
| NL2SQL | SQL generation, AST safety guard, repair loop, narration | Schema retrieval, ACL pushdown, budget allocation |
| Agent | State machine, step semantics, HITL gates | Per-step context compilation, trust tiers, replay |

An import-linter contract enforces the direction: `features` may not import `flows`.

## Rationale

**An abstraction validated by a single consumer is speculation.** The kernel's claim is
that context assembly can be *planned* rather than hand-written. That claim is only
credible if genuinely different consumers can be expressed in the same operator algebra.
Three were chosen because they stress different parts of it:

| Flow | Stresses | Would falsify the kernel if… |
|---|---|---|
| RAG | Fusion and compression across heterogeneous scorers | …RRF across incomparable score distributions didn't work |
| NL2SQL | Precision, fail-closed table authorization | …the planner couldn't express hard inclusion/exclusion |
| Agent + MCP | Trust tiering, multi-turn budgets, replay | …tiers weren't monotone, or bundles weren't replayable |

**Why the reversal on NL2SQL was correct.** The original reasoning optimized for "don't
repeat yourself" and missed the stronger argument. The differentiation was never in
*avoiding* NL2SQL — it is that the stages previously hand-wired as a fixed 7-step state
machine become **operators the compiler plans over**. That is the same leap SQL made from
hand-written access plans to a cost-based optimizer, and demonstrating it against prior
work makes the progression legible rather than repetitive.

**The reuse is real, and it is the evidence.** Storing warehouse schema as *memory claims*
(predicate `has_table` / `has_column`) rather than in a bespoke `table_metadata` table
means:
- Schema retrieval is a `MemoryScan` — no new retrieval code.
- Table authorization is the same ACL pushdown as everywhere else — an unauthorized table
  is never in the bundle to begin with.
- **Schema drift inherits bitemporal versioning for free.** "What did this schema look like
  in March?" needs no code at all.

That third property was not designed for. It fell out of the abstraction, which is the
strongest available evidence that the abstraction is correct rather than merely tidy.

## Alternatives considered

**Three independent pipelines.** Faster to build, no coupling. Rejected: three copies of
retrieval, ranking, and authorization, which drift immediately. More decisively, it would
leave the central thesis unproven — a compiler with no consumers is a library nobody has
validated.

**One flow only (RAG), kernel proven by unit tests alone.** Tempting under time pressure.
Rejected: unit tests prove the code runs, not that the abstraction is right. Abstractions
fail by being *insufficiently general*, and only a second and third consumer reveal that.

**A shared "retrieval service" without a compiler.** A middle path — shared retrieval, but
each flow assembles its own prompt. Rejected: assembly is where budget allocation, conflict
resolution, and trust fencing happen. Leaving those to flows means three implementations of
the security-relevant part.

## Consequences

**Positive** — the kernel abstraction is empirically validated, not asserted; retrieval,
authorization, and budgeting have exactly one implementation; a fourth flow costs a
template and an ingestion path; the NL2SQL flow demonstrates measurable evolution beyond
prior work rather than repetition.

**Negative** — the kernel must be general enough for all three, which is real design
pressure and will occasionally force a compromise no single flow would have chosen; a
kernel bug affects everything; flows cannot ship until the kernel exists (M5 gates M6, M8,
M9), which front-loads risk.

**Front-loaded risk, deliberately accepted.** M0–M5 produce no user-facing flow. That is
uncomfortable and it is correct: building flows first would produce three retrieval
implementations that then have to be torn out. The mitigation is that M5's exit criteria
are demonstrable on their own — `EXPLAIN` output is a compelling artifact before any flow
exists.

**Watch for the failure signal.** If a flow ever needs to reach around the kernel to
retrieve something directly, that is evidence the operator algebra is incomplete. The
correct response is to add an operator, never to let the flow do its own retrieval. The
import-linter contract makes the wrong response fail CI rather than pass review.
