# ADR-0005 — Lagrangian-relaxed greedy allocation over exact optimization

**Status:** Accepted · **Date:** 2026-07-26

## Context

The compiler must allocate a hard budget across competing candidates. Formally:

```
maximize    Σ uᵢ · xᵢ                                  (total utility)
subject to  Σ tᵢ · xᵢ  ≤  TokenBudget
            max over critical path of lᵢ  ≤  LatencyBudget
            Σ cᵢ · xᵢ  ≤  ComputeBudget
            floorₛ ≤ Σ_{i ∈ section s} tᵢ · xᵢ ≤ ceilₛ    ∀ sections s
```

This is a multi-dimensional knapsack with side constraints — NP-hard in general.

## Decision

**Lagrangian-relaxed greedy on utility density (`uᵢ / tᵢ`), followed by a bounded
local-improvement pass. `O(n log n)`, deterministic, no external solver.**

```
1. Reserve section floors (hard, non-negotiable — the policy section always survives)
2. Compute density uᵢ/tᵢ for remaining candidates
3. Sort descending; admit while all constraints hold and section ceilings permit
4. Local improvement: bounded swap search for pairs where exchanging an admitted item
   for an unadmitted one raises total utility
5. Record every admission and eviction with a reason → allocator_trace
6. Report which constraint bound → binding_constraint
```

## Rationale

**The optimality gap is dwarfed by the estimation error.** Greedy density on knapsack is
typically within a few percent of optimal. But `uᵢ` — the expected utility of a candidate
— is estimated from an EWMA of noisy downstream feedback and carries error of tens of
percent. Solving exactly against inputs that wrong is precision theatre: it produces
confident answers to the wrong question, and it invites the reader to assume the utility
model is more trustworthy than it is.

**Determinism is required, not preferred.** Context bundles are content-addressed and
golden-fixture-tested ([ADR-0001](ADR-0001-context-as-compiled-artifact.md)). An ILP
solver that returns a different optimum among ties — or behaves differently across
versions and platforms — breaks reproducibility, which is a load-bearing property.
Deterministic tiebreaks (by candidate ID) are part of the algorithm, not an afterthought.

**Explainability falls out for free.** Greedy admission produces a natural narrative:
*"admitted in density order until the latency constraint bound; this item was evicted
because its section ceiling was reached."* An ILP returns an optimal vector with no
account of itself. Since `EXPLAIN` is the project's flagship feature, an algorithm that
cannot explain its own decisions is disqualified regardless of its optimality.

**No solver dependency.** PuLP/OR-Tools add a heavyweight dependency, a licensing
question, and unpredictable latency for an operation on the critical path with a
sub-15 ms budget.

## Why section floors and ceilings exist

Without floors, a single high-scoring document evicts the entire conversation history —
a failure mode that presents as amnesia and is maddening to diagnose, because the
retrieval "worked correctly." Floors make certain sections non-negotiable regardless of
score. Ceilings prevent one memory kind from monopolizing the budget.

These constraints make the problem harder to solve exactly and easier to solve
*acceptably* — another reason exact optimization is poor value here.

## The `binding_constraint` output

The allocator reports which resource it actually ran out of. Under local CPU inference
this is usually `latency_ms`; under hosted inference, usually `tokens`. That single field
turns "the answer was bad" into "you were latency-bound — raise the budget or change
model tier." It is arguably more valuable to a user than the allocation itself.

## Alternatives considered

**Exact ILP.** Optimal, explainable only as a number, non-deterministic under ties, heavy
dependency, unpredictable latency. Rejected.

**Fixed proportional split (e.g. 30% conversation, 40% documents, 30% memory).** Trivial
and predictable. Rejected: it ignores utility entirely. A request with no relevant
documents still reserves 40% for them, wasting budget that conversation history needed.

**Let the model decide via a tool call.** Non-deterministic, unbudgetable (the model
cannot estimate retrieval costs), and it places allocation on the wrong side of the
prompt-injection boundary.

**Learned allocator (RL / bandit).** Interesting, and the natural long-term direction.
Rejected now: requires substantial feedback data that does not exist yet, is
non-deterministic, and is unexplainable. The `utility_prior` EWMA is a deliberate first
step toward this without sacrificing determinism.

## Consequences

**Positive** — deterministic, fast (`O(n log n)`), dependency-free, self-explaining,
handles floors/ceilings naturally, and reports its binding constraint.

**Negative** — not optimal; pathological inputs exist where greedy is meaningfully worse
(many items with near-identical density and tight ceilings); the local-improvement pass is
bounded and can miss improvements.

**Accepted risk and its guard:** if measurement ever shows the optimality gap matters more
than the estimation error, the allocator is one module (`optimizer/allocator.py`) behind a
stable interface. Swapping it is contained. The Hypothesis test asserting *"assembled
tokens never exceed budget across randomized configurations"* is the property that must
survive any replacement.
