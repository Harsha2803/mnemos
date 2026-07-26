# TRACKER — single source of truth for "what next"

> **If you are an agent picking up this project: read this file first, in full, before
> reading anything else or writing any code.** It tells you the current state, the
> constraints you must not violate, and the exact next task. When you finish work,
> update this file *in the same commit* — a stale tracker is worse than none.

**Last updated:** 2026-07-26 · **Phase:** Architecture complete, implementation not started
**Current milestone:** M0 — Foundations · **Next task:** `M0-T1`

---

## 0. Agent operating instructions

1. **Read in this order:** this file → [`docs/Architecture.md`](docs/Architecture.md) →
   the ADRs referenced by your task → [`docs/CodingStandards.md`](docs/CodingStandards.md).
2. **Work one task at a time**, in the order given in §4. Tasks have IDs
   (`M0-T1`, `M3-T5`, …) defined in [`docs/ImplementationPlan.md`](docs/ImplementationPlan.md).
3. **Do not skip ahead.** Later tasks assume earlier ones exist. If a task appears
   blocked, record why in §6 rather than working around it.
4. **Every task ends with:** code + tests + green CI + docs updated if behaviour changed
   + this tracker updated + a conventional commit.
5. **Do not re-litigate decisions in §2.** They are settled and recorded in ADRs. If you
   believe one is wrong, write a new ADR superseding it — do not silently deviate.
6. **Never introduce a placeholder, a `TODO`, or a stubbed function.** If a task is too
   large to finish, split it into sub-tasks (`M3-T5a`, `M3-T5b`) and complete the first.

---

## 1. What this project is (30-second version)

**Mnemos — a context operating system for AI agents.**

Thesis: *context is a compiled artifact, not a concatenated string.* A cost-based
compiler takes a request + policy + budget and emits a content-addressed,
provenance-attributed, replayable **context bundle**, with `EXPLAIN` for every decision.

- **Kernel:** memory (bitemporal claims) · retrieval (ACL-pushed-down) · context compiler
- **Flows:** RAG over PDFs · NL2SQL · Agent + MCP tools
- **Constraint:** runs at **zero cost** on local models; hosted providers are opt-in config.

Full detail: [`docs/Architecture.md`](docs/Architecture.md).

---

## 2. Non-negotiable constraints — do not violate, do not re-decide

| # | Constraint | Authority |
|---|---|---|
| C1 | **Zero paid dependencies in the default path.** No API key required for any capability. | [ADR-0008](docs/ArchitectureDecisionRecords/ADR-0008-local-first-inference.md) |
| C2 | **Domain layers import no I/O.** No sqlalchemy/httpx/redis/fastapi in `*/domain/`. CI-enforced. | [ADR-0003](docs/ArchitectureDecisionRecords/ADR-0003-feature-first-clean-architecture.md) |
| C3 | **`features` may never import `flows`.** CI-enforced. | [ADR-0011](docs/ArchitectureDecisionRecords/ADR-0011-three-flows-as-kernel-consumers.md) |
| C4 | **Fail closed.** Absence of an explicit allow is a deny. Unavailable PDP denies. | Architecture P3 |
| C5 | **ACL predicates are pushed into index scans. Post-filtering is banned.** | [ADR-0004](docs/ArchitectureDecisionRecords/ADR-0004-pgvector-over-dedicated-vector-db.md) |
| C6 | **Memory is never overwritten.** Updates supersede. Deletion is a separate, audited operation. | [ADR-0006](docs/ArchitectureDecisionRecords/ADR-0006-bitemporal-memory-model.md) |
| C7 | **No `datetime.now()` or `uuid4()` in domain/application code.** Use injected `Clock` / `IdGenerator`. | CodingStandards §5 |
| C8 | **Every external call has an explicit timeout.** No exceptions. | CodingStandards §3 |
| C9 | **No magic numbers.** Every tunable is a named setting with a documented default. | CodingStandards §7 |
| C10 | **No placeholders, no `TODO` comments, no stubbed returns.** | Project rule |
| C11 | **Never commit secrets.** Never use the work email/account (`@jktech.com`, `harshaJKT`). | [ADR-0012](docs/ArchitectureDecisionRecords/ADR-0012-licensing-and-openness.md) |
| C12 | **CPU inference is offloaded to a thread pool**, never called inline in an async path. | CodingStandards §3 |

---

## 3. Current state

### Done
- ✅ Full architecture documentation set (`docs/`, 11 documents + 12 ADRs)
- ✅ Repo initialized, `.gitignore`, repo-local personal git identity

### Not started
- ⬜ Everything else. **No implementation code exists yet.**

### Environment facts
| Fact | Value |
|---|---|
| Repo root | `/home/shreeharsha/Personal/Projects/Resume_001/mnemos` |
| Python | 3.12.3 |
| Git identity (repo-local) | `Cheella Sree Harsha <cheellasreeharsha2803@gmail.com>` |
| GitHub account | `Harsha2803` (personal) — **never** `harshaJKT` |
| Repo visibility | Private until v0.2 |

---

## 4. Task board

Legend: ⬜ not started · 🟡 in progress · ✅ done · 🚫 blocked (see §6)

### M0 — Foundations ⬜  *(next up)*
| ID | Task | Status |
|---|---|---|
| M0-T1 | `pyproject.toml`, src-layout, Ruff + mypy strict, pre-commit | ⬜ |
| M0-T2 | `core/config.py` — BaseSettings, fail-fast, `ModelTier` enum | ⬜ |
| M0-T3 | `core/errors.py` — hierarchy + RFC 9457 mapping | ⬜ |
| M0-T4 | `core/{ids,clock,canonical,result,pagination}.py` | ⬜ |
| M0-T5 | `core/telemetry.py` — OTel + structlog contextvars | ⬜ |
| M0-T6 | `core/di.py` — container + composition root | ⬜ |
| M0-T7 | `platform/db` — async engine, session, UnitOfWork, RLS GUC | ⬜ |
| M0-T8 | Alembic + `0001_initial_extensions` | ⬜ |
| M0-T9 | `deploy/compose` — full free stack | ⬜ |
| M0-T10 | FastAPI skeleton, correlation-ID middleware, `/healthz` `/readyz` | ⬜ |
| M0-T11 | `.importlinter` contracts 1–5 | ⬜ |
| M0-T12 | GitHub Actions CI, all gates | ⬜ |
| M0-T13 | `Makefile` | ⬜ |

### M1 — Identity, tenancy, PDP ⬜ (M1-T1 … M1-T12)
### M2 — Inference gateway, local-first ⬜ (M2-T1 … M2-T12)
### M3 — Memory substrate ⬜ (M3-T1 … M3-T14)
### M4 — Retrieval fabric ⬜ (M4-T1 … M4-T12)
### M5 — Context Compiler ⭐ ⬜ (M5-T1 … M5-T19) ← **the thesis milestone**
### M6 — Flow A: RAG ⬜ (M6-T1 … M6-T9)
### M7 — Knowledge graph ⬜ (M7-T1 … M7-T6)
### M8 — Flow B: NL2SQL ⬜ (M8-T1 … M8-T12)
### M9 — Agent runtime ⬜ (M9-T1 … M9-T9)
### M10 — Flow C: MCP service ⬜ (M10-T1 … M10-T12)
### M11 — Dashboard ⬜ (M11-T1 … M11-T10)
### M12 — Hardening ⬜ (M12-T1 … M12-T10)

Full task descriptions and exit criteria:
[`docs/ImplementationPlan.md`](docs/ImplementationPlan.md).

---

## 5. NEXT TASK — fully specified

### `M0-T1` — Toolchain and package skeleton

**Read first:** [`docs/CodingStandards.md`](docs/CodingStandards.md) §1–2,
[`docs/FolderStructure.md`](docs/FolderStructure.md) §1–2.

**Deliverables**

1. `pyproject.toml` — hatchling backend, `src/` layout, package `mnemos`, Python `>=3.12`.
   - Runtime deps: `fastapi`, `uvicorn[standard]`, `pydantic>=2.7`, `pydantic-settings`,
     `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic`, `redis`, `neo4j`, `celery`,
     `httpx`, `structlog`, `tenacity`, `opentelemetry-sdk`,
     `opentelemetry-instrumentation-fastapi`, `uuid-utils` (UUIDv7), `anyio`, `orjson`.
   - Dev deps: `ruff`, `mypy`, `import-linter`, `pytest`, `pytest-asyncio`, `pytest-cov`,
     `hypothesis`, `testcontainers[postgres]`, `bandit`, `pip-audit`.
   - Ruff and mypy config exactly as in CodingStandards §1 (copy it — do not improvise).
2. Directory skeleton with `__init__.py` in each, matching FolderStructure §2:
   `src/mnemos/{core,platform,features,flows,entrypoints}/` and the subpackages listed
   there. Empty packages are fine at this stage; **no stub functions**.
3. `.pre-commit-config.yaml` — `ruff --fix`, `ruff-format`, `mypy`, `gitleaks`,
   trailing-whitespace, end-of-file-fixer, `check-added-large-files`.
4. `tests/` skeleton with `conftest.py` and `tests/unit/test_smoke.py` asserting the
   package imports and exposes `__version__`.

**Acceptance criteria**
- `pip install -e ".[dev]"` succeeds from a clean venv.
- `ruff check . && ruff format --check .` passes.
- `mypy src/` passes with `strict = true` and zero ignores.
- `pytest` passes.
- `pre-commit run --all-files` passes.

**Commit:** `chore(build): add toolchain, src-layout skeleton, and pre-commit gates`

**Then:** mark `M0-T1` ✅ in §4, set §5 to `M0-T2`, update the header date, commit.

---

## 6. Blockers and open questions

*None currently.*

Open architectural questions (decide with evidence, not opinion — see
[`docs/Roadmap.md`](docs/Roadmap.md) §5): **Q1** utility model learning · **Q2** Postgres
FTS vs BM25 · **Q3** working-memory store · **Q4** semantic bundle caching ·
**Q5** 3B model adequacy for NL2SQL · **Q6** audit log hash chaining.

---

## 7. Update protocol

When you finish a task, in the **same commit**:

1. Flip its status to ✅ in §4.
2. Rewrite §5 to fully specify the next task — deliverables, acceptance criteria,
   commit message, and which docs to read first. Match the level of detail above; the
   next agent may have no context beyond this file.
3. Update the header (`Last updated`, `Current milestone`, `Next task`).
4. Add anything discovered that a future session would otherwise have to rediscover:
   a version pin that mattered, a workaround, a surprising behaviour — put it in §3
   *Environment facts* or §6.
5. If you made an architectural decision, add an ADR and log it in
   [`docs/DecisionLog.md`](docs/DecisionLog.md). Do not bury a decision in a commit
   message.

**If you deviated from a documented design, say so explicitly in §6.** An undocumented
deviation is the single most expensive thing to discover later, because the docs will be
trusted and will be wrong.
