# ADR-0001 — Context is a compiled artifact, not a concatenated string

**Status:** Accepted · **Date:** 2026-07-26 · **Supersedes:** — · **Superseded by:** —

## Context

An LLM's behaviour is a function of exactly one input: the token sequence it receives.
Every other concern — retrieval quality, memory, personalization, safety, cost — reduces
to *what ends up in that sequence and why*.

In practice that sequence is assembled by imperative glue: fetch N turns, embed the
query, take top-k, concatenate, truncate. Four consequences follow, and all of them get
worse with scale:

1. **Not explainable** — no answer to "what was in context, and what was left out?"
2. **Not budgeted** — the token window is a contended resource with no arbitration.
   The last writer wins; the most important source silently loses.
3. **Not governed** — access control applied after retrieval leaks existence through
   result-count side channels and destroys recall.
4. **Not reproducible** — the same request an hour later yields different context, so
   the thing that actually determines model behaviour cannot be regression-tested.

## Decision

**Model context assembly as a multi-phase compiler with a cost-based optimizer.**

```
ContextRequest → Bind → LogicalPlan → CostBasedOptimize → PhysicalPlan
              → Execute (deadline-bounded DAG) → Refine → Assemble → ContextBundle
```

The output is a **`ContextBundle`**: content-addressed by SHA-256 over its canonical
form, carrying a manifest in which every included item records its source, version,
score, producing operator, token count, trust tier, and **the policy rule that admitted
it**. `EXPLAIN CONTEXT` is a first-class API returning the logical plan, physical plan,
per-operator actuals, and the allocator's admission and eviction decisions with reasons.

## Rationale

The database analogy is load-bearing, not decorative. Databases faced this exact problem
— hand-written access plans that were unexplainable, unbudgeted, and unreproducible —
and solved it with a cost-based optimizer plus `EXPLAIN`. That solution is forty years
proven, and it tells us what to build next at every decision point.

Reframing gives four properties that are otherwise unreachable:

| Property | Mechanism |
|---|---|
| Explainability | `EXPLAIN` over a materialized plan |
| Resource governance | Optimizer allocates a hard budget across competing claimants |
| Correct authorization | Predicate pushdown into index scans, as a rewrite rule |
| Reproducibility | Content-addressed bundles + pinned non-deterministic outputs |

Reproducibility is the one that compounds. Because bundles are deterministic, **golden
bundle fixtures** become possible — frozen `(request, versions) → digest` triples in CI.
A change that silently alters assembled context fails the build. Nothing else in this
design space offers a regression test for prompt content.

## Alternatives considered

**Imperative pipeline with a config file.** Cheaper. But configuration cannot express
"when the latency budget binds, drop graph expansion before conversation history" — that
is a decision requiring cost estimates and a solver. Config-driven pipelines devolve into
if-ladders encoding an implicit, unexamined cost model.

**Let the model decide via tool calls (agentic retrieval).** Flexible, and the model
sometimes chooses well. But it is non-deterministic, unbudgetable (the model cannot know
what a retrieval costs), unauditable, and — critically — it puts retrieval decisions on
the far side of the prompt-injection boundary. The compiler retains authority over what
enters context; the model receives the result. That ordering is a security property.

**Fixed multi-stage pipeline (the prior-work approach).** A hand-written 7-step state
machine works and is debuggable. It is what this design evolves *from*. Its limit is that
adaptation requires code changes: every new trade-off becomes a new branch. The compiler
replaces branches with a cost model.

## Consequences

**Positive** — `EXPLAIN` turns "the agent hallucinated" from a dead end into a
plan-reading exercise. Budgets are enforced structurally, not by hoping. Authorization is
correct by construction. Context becomes regression-testable. Adding a retrieval source
is adding an operator with a cost vector, not editing an assembly function.

**Negative** — substantially more machinery than string concatenation: an IR, an operator
algebra, rewrite rules, a statistics catalog, an allocator, an executor. The optimizer is
only as good as its statistics, and cold-start quality depends on defaults being sane.
Utility estimation is the weakest link and is genuinely hard to get right.

**Mitigation for the weak link:** utility priors start static and documented, and only
become adaptive (EWMA from feedback) if measurement shows the adaptive version is better.
Recorded as open question Q1 in [Roadmap §5](../Roadmap.md#5-open-questions).

## Verification

- Hypothesis test: assembled tokens never exceed budget across randomized configurations.
- Determinism test: identical request + pinned versions ⇒ identical digest.
- Golden bundle CI gate ([M5-T18](../ImplementationPlan.md#m5--the-context-compiler-)).
- `EXPLAIN` names the binding constraint and lists every eviction with a reason.
