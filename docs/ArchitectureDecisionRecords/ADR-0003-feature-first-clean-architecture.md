# ADR-0003 — Feature-first layout with clean-architecture layers, enforced by CI

**Status:** Accepted · **Date:** 2026-07-26

## Context

Two organizing axes are available: by technical layer (`domain/`, `application/`,
`adapters/` at the top) or by feature (`memory/`, `context/`, `retrieval/` at the top).
The choice determines how a typical change feels for the life of the project.

## Decision

**Feature-first at the top level; clean-architecture layers inside each feature;
boundaries enforced by `import-linter` in CI.**

```
features/memory/
├── domain/          # zero I/O imports
├── application/     # use cases
├── adapters/        # implements domain/ports.py
├── api/             # driving adapter
├── tasks/           # background jobs
└── contracts.py     # the ONLY module other features may import
```

Five CI-enforced contracts: domain purity, layer ordering, feature independence,
flows-depend-on-kernel-never-the-reverse, and core-depends-on-nothing-internal.

## Rationale

**Changes are local.** Adding a memory lifecycle policy touches
`memory/domain/policies.py`, `memory/tasks/`, and a test. Under layer-first organization
the same change is scattered across three top-level directories, and reviewing it
requires holding the whole tree in mind.

**Ownership is legible.** "Who owns memory?" has an answer. Under layer-first, ownership
is a matrix and nobody owns anything end to end.

**Deletion is possible.** Removing a feature means removing a directory. Layer-first
makes removal an archaeology exercise, which is why dead code accumulates there.

Layering is retained *inside* features because the property that matters — the domain
cannot import SQLAlchemy — is orthogonal to top-level organization. Feature-first without
inner layering is just a package tree with better names.

**`contracts.py` is what prevents the known failure mode.** Feature-first degrades into a
ball of mud with directories when features start importing each other's internals. A
single published module per feature, enforced by an independence contract, is the
difference between modules and folders.

**CI enforcement is the actual decision.** Architecture that is documented but not
enforced is documentation of intent. Every codebase has a diagram showing clean layers
and an import graph showing otherwise. The `.importlinter` file is the architecture; this
document is its rationale.

## Alternatives considered

**Layer-first (`domain/`, `application/`, `adapters/` at top).** The canonical Clean
Architecture presentation. Works for small systems with one bounded context. Rejected:
this system has clearly distinct contexts (memory, retrieval, context compilation,
identity) and layer-first scatters each one.

**Flat modules, no layering.** Fastest to start. Rejected: within months the domain
imports the ORM, tests require a database, and the ports that make adapters swappable
never materialize — which would break the "swap pgvector for Qdrant with one adapter"
claim the design depends on.

**Separate packages per feature (monorepo).** Strongest enforcement — imports fail at
packaging time. Rejected as premature: a solo project would pay continuous versioning and
release overhead to prevent a problem `import-linter` already prevents at near-zero cost.

## Consequences

**Positive** — local changes, clear ownership, deletable features, CI-verified
boundaries, testable domain logic without infrastructure.

**Negative** — more directories; some duplication across features (each has its own
`schemas.py`); developers unfamiliar with the pattern need the convention explained,
which is why every feature has an identical structure with no exceptions.

**Accepted rigidity:** every feature has all five directories even when one is nearly
empty. Predictability across features is worth more than a locally-optimal layout in any
one of them — a reader should never have to learn a new structure.
