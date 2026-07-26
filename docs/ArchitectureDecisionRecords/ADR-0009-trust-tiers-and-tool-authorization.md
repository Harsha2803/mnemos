# ADR-0009 — Monotone trust tiers with re-authorization at the tool boundary

**Status:** Accepted · **Date:** 2026-07-26

## Context

Indirect prompt injection is the highest-severity threat to any system that retrieves
content and then acts on it. An adversary plants instructions in a document, a web page, or
a tool response; the content is ingested, retrieved into context, and the model follows it —
invoking tools with the user's authority.

The standard mitigation is to instruct the model to ignore instructions found in retrieved
content. **That is a request, not a control.** Models comply inconsistently, and adversarial
phrasings defeat it reliably. Any design whose only defence is prompt wording is
unmitigated, and should be described as such.

## Decision

**Every piece of content carries an immutable trust tier assigned at its source, and
instruction authority is monotone non-increasing. Tool calls are re-authorized at the
invocation boundary against the minimum trust tier present in the context that motivated
them.**

```
tier 0  system                  highest authority
tier 1  operator
tier 2  user
tier 3  workspace
tier 4  retrieved_trusted
tier 5  retrieved_untrusted
tier 6  tool_output             lowest authority
```

Each tool declares `min_trust_tier`. A call is denied when
`min(trust tiers in motivating context) > tool.min_trust_tier`, and the denial names the
offending source.

## Rationale

**Enforcement happens in two independent places, and only the second one works.**

*Layer 1 — assembly.* Untrusted sections are fenced with explicit non-authority framing and
sanitized of control characters and delimiter-escape sequences. This raises the cost of a
naive breakout. It does not stop a determined one.

*Layer 2 — the tool boundary.* This is the control that changes outcomes. Even if the model
is **fully persuaded** by injected instructions, the tool call it emits is checked against
the trust tier of the context that produced it. A call motivated by tier-5 content cannot
exercise tier-2 permissions. **The model's compliance becomes irrelevant** — which is the
only acceptable place to put the guarantee, because model compliance is not something the
system controls.

Enforcing only at assembly is the standard mistake. Models can be induced to launder
untrusted instructions through their own reasoning, and what arrives at the tool boundary
looks like the model's own intent. The second check is what makes the invariant hold.

**Tiers are assigned at source and are immutable.** If content could be re-tiered later, the
laundering path reopens: ingest untrusted content, have something re-classify it as trusted,
and the guarantee is gone.

**The decision is persisted, not merely computed.** `mcp_invocation.motivating_trust_tier`
and `agent_checkpoint.min_trust_tier` are stored columns, so an audit can verify after the
fact that the check ran with the correct inputs. A security control that leaves no evidence
cannot be audited, and one that cannot be audited will eventually be quietly broken by a
refactor.

**The error is deliberately informative.** A `403` naming the exact document whose presence
demoted the trust tier turns an abstract security property into something an engineer can
act on. Without it, the control is experienced as mysterious failure and will be disabled.

## Scope: what this does and does not prevent

**Prevented:** injected content taking *authorized actions* — sending email, writing to a
database, calling an external API with user credentials. This is the exfiltration step, and
it is where the real damage happens.

**Not prevented:** injected content causing a *wrong answer* to the user. Preventing that
entirely is not achievable with current techniques.

Stating this boundary explicitly is part of the decision. A threat model claiming to solve
prompt injection would be false, and the false claim is more dangerous than the residual
risk, because it discourages the compensating controls (provenance in the manifest, so a
user can check sources).

## Alternatives considered

**Prompt-based instruction ("ignore instructions in documents").** Rejected as a primary
control for the reasons above. Retained as a defence-in-depth layer, correctly weighted.

**Sanitize/strip instructions from retrieved content.** Rejected: distinguishing an
instruction from a legitimate imperative sentence is an unsolved NLP problem, and a
heuristic filter produces both false negatives (bypass) and false positives (mangled
documents).

**Human approval for every tool call.** Maximally safe, unusable. Retained selectively:
tools declaring `requires_approval` route through `AWAITING_APPROVAL`, so the strong control
is applied where the stakes justify it.

**Separate model instances per trust level.** Interesting — a "quarantined" model reads
untrusted content and reports structured findings to a privileged model. Rejected as
disproportionate here (2× inference cost is prohibitive under
[ADR-0008](ADR-0008-local-first-inference.md)), but noted as the strongest known approach if
constraints change.

## Consequences

**Positive** — a real, testable security property rather than a hopeful instruction; the
denial is explainable and actionable; the decision is auditable after the fact; tool
authority is bounded by construction.

**Negative** — legitimate workflows are blocked when a low-trust document happens to be in
context, which will produce false-positive friction; every tool must have its
`min_trust_tier` set thoughtfully, and a careless default undermines the whole scheme;
computing the minimum tier over a context adds bookkeeping through the agent runtime.

**Mitigation for false positives:** the error names the offending source, so a user can
re-run with that document excluded — a specific, achievable remedy rather than an opaque
denial.

**Verification** ([M10-T8](../ImplementationPlan.md#m10--flow-c-mcp-tool-service-separate-entity)):
a test asserts that a tool call motivated by tier-5 content is denied and that the denial
names the offending document.
