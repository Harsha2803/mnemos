# ADR-0012 — Apache License 2.0

**Status:** Accepted · **Date:** 2026-07-26

## Context

The repository is intended to become a public open-source project and to be read by
engineers evaluating the author's work. The licence choice affects both how it can be used
and how it is perceived.

There is also a practical concern specific to this situation: the author is employed, and
the project must be unambiguously personal work created outside employment, on personal
equipment, in a personal account.

## Decision

**Apache License 2.0.** Repository private until v0.2 (kernel + one working flow), public
thereafter.

Additionally:
- Repo-local git identity set to the personal account and email; the machine's global
  work identity is never used for this repository.
- No employer code, configuration, credentials, data, or proprietary domain vocabulary
  enters the repository at any point.
- `NOTICE` and a `CONTRIBUTING.md` with a DCO sign-off requirement before going public.

## Rationale

**Apache 2.0 over MIT — the express patent grant.** Both are permissive; the material
difference is that Apache 2.0 includes an explicit patent licence from contributors and a
patent-retaliation clause. For infrastructure that companies might adopt, corporate legal
review treats this as a meaningful reduction in risk. MIT's silence on patents is a known
friction point for enterprise adoption, and adoption is the point of publishing.

**Apache 2.0 over AGPL.** AGPL would prevent a company from running a modified version as
a hosted service without releasing changes. That protection is worth having when the goal
is a commercial product. Here the goal is adoption and technical credibility, and AGPL is
disqualifying at most companies' open-source review — it would reduce the audience that
can read and evaluate the code.

**Apache 2.0 over BSL / Elastic-style source-available.** These are commercial-protection
licences. Applying one to a portfolio project signals commercial intent that does not
exist, and excludes it from being genuinely open source.

**Apache 2.0 is also the norm in this ecosystem** — Kubernetes, Kafka, Spark, LangChain,
LlamaIndex, and Qdrant all use it. Matching the ecosystem's default means the licence is a
non-question for anyone evaluating the project.

**Why private until v0.2.** A public repository whose first several dozen commits are
documentation tells a weaker story than one that opens with a runnable system. The decision
is cheap to reverse in one direction and impossible in the other — early commits, once
public, are public.

## Employment separation, stated explicitly

This matters more than the licence text and is recorded here because it is the part most
easily neglected:

- All work on personal equipment, personal time, personal GitHub account (`Harsha2803`).
- Repo-local `user.email` set to the personal address; the global config remains the work
  identity and is untouched. Commits authored under an employer email create avoidable
  ambiguity about IP ownership, and the attribution is permanent once pushed.
- No employer source, schemas, prompts, domain registries, customer data, or internal
  documentation is copied. **Patterns and lessons are portable; artifacts are not.** Prior
  professional experience informs the architecture — the transactional outbox, the
  single-owner retry policy, fail-closed authorization — but every line here is written
  fresh against public documentation.
- If employment terms make personal open-source work ambiguous, obtain written clarification
  before making the repository public. This is a genuine risk, it is cheap to resolve in
  advance, and it is extremely expensive to resolve afterwards.

## Alternatives considered

| Licence | Why not |
|---|---|
| MIT | Simpler and widely liked, but silent on patents — a real friction point in corporate review |
| AGPL-3.0 | Blocked at most companies' OSS review; would shrink the evaluating audience |
| BSL 1.1 | Signals commercial intent that does not exist; not open source |
| Unlicense / public domain | No patent grant, no liability disclaimer, unclear in some jurisdictions |
| No licence | Legally "all rights reserved" — nobody can use it, and it reads as carelessness |

## Consequences

**Positive** — maximum adoptability; express patent grant reduces corporate review
friction; matches ecosystem convention; permits commercial use, which is what makes it
credible infrastructure rather than a demo.

**Negative** — permissive licensing allows use without contribution back, which is
irrelevant to this project's goals; Apache 2.0 requires preserving `NOTICE` and stating
changes, a small ongoing obligation.

**Action before going public:** add `LICENSE`, `NOTICE`, `CONTRIBUTING.md` (DCO),
`CODE_OF_CONDUCT.md`, and `SECURITY.md` with a disclosure contact. A security-relevant
project without a disclosure path is a project that will receive its first vulnerability
report as a public GitHub issue.
