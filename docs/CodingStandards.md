# Coding Standards

Rules, not suggestions. Everything here is machine-enforced where it can be; the rest is
review policy. Each rule states *why*, because a rule whose rationale is unknown gets
worked around the first time it is inconvenient.

---

## 1. Toolchain

| Tool | Role | Enforcement |
|---|---|---|
| Ruff | Lint + format (replaces Black, isort, flake8) | `--fix` in pre-commit, `--check` in CI |
| mypy | Type checking, `strict = true` | CI blocking |
| import-linter | Architecture boundaries | CI blocking |
| pytest + pytest-asyncio | Tests | CI blocking |
| Hypothesis | Property tests for pure policy functions | CI blocking |
| testcontainers | Real Postgres/Redis/Neo4j in integration tests | CI blocking |
| bandit + pip-audit | SAST + dependency CVEs | CI blocking |
| Alembic | Migrations, with a tested downgrade | CI blocking |

`pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E","F","W","I","N","UP","ANN","ASYNC","S","B","A","C4","DTZ",
          "T20","PT","RET","SIM","TCH","ARG","PTH","ERA","PL","RUF"]
ignore = ["ANN101","ANN102"]

[tool.mypy]
python_version = "3.12"
strict = true
disallow_any_explicit = true
warn_unreachable = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
addopts = "--strict-markers --strict-config -q"
asyncio_mode = "auto"
```

`DTZ` (naive datetimes) and `ASYNC` (blocking calls in async functions) are selected
deliberately — they catch the two bug classes this system is structurally most exposed
to. `T20` bans stray `print`. `ERA` bans commented-out code.

## 2. Typing

**`strict = true`, and `Any` requires a written justification.**

```python
# NO — dict[str, Any] is a type-checker opt-out with extra steps
async def compile_context(request: dict[str, Any]) -> dict[str, Any]: ...

# YES
async def compile_context(request: ContextRequest) -> ContextBundle: ...
```

Domain models are frozen Pydantic models or dataclasses:

```python
class Claim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ClaimId
    subject: SubjectRef
    predicate: Predicate
    object: str
    validity: ValidityInterval
    belief: BeliefInterval
    trust_tier: TrustTier
    confidence: Confidence
```

**Newtypes for identifiers, not bare `UUID`:**

```python
ClaimId    = NewType("ClaimId", UUID)
OrgId      = NewType("OrgId", UUID)
BundleDigest = NewType("BundleDigest", bytes)
```

Every ID in this system is a UUID. Without newtypes, `revoke(user_id, org_id)` accepts
the arguments in either order and the type checker is satisfied. That bug is silent, and
in a multi-tenant system it is a data leak.

**Constrained scalars over raw primitives:**

```python
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
TrustTier  = Annotated[int, Field(ge=0, le=6)]
TokenCount = Annotated[int, Field(ge=0)]
```

The invariant lives in the type, so it cannot be forgotten at one of thirty call sites.

## 3. Async

**Async all the way down. One blocking call in an async path stalls the entire event
loop for every concurrent request.**

```python
# NO — blocks the loop
def load_config() -> Config:
    return json.loads(Path("cfg.json").read_text())

# YES
async def load_config() -> Config:
    return json.loads(await anyio.Path("cfg.json").read_text())
```

**CPU-bound and model inference work goes to a thread or process pool**, never inline:

```python
# Embedding is CPU-bound under sentence-transformers. Inline, it freezes the loop
# for the full inference duration — ~10ms per call, but serialized across every
# concurrent request, which is how a 10ms operation becomes a 2s p99.
async def embed(self, texts: Sequence[str]) -> list[Vector]:
    return await anyio.to_thread.run_sync(self._model.encode, texts)
```

**Structured concurrency only.** `asyncio.TaskGroup`, never bare `create_task`:

```python
async def execute_wave(self, ops: Sequence[Operator]) -> list[CandidateSet]:
    results: list[CandidateSet] = []
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(self._run_with_deadline(op)) for op in ops]
    return [t.result() for t in tasks]
```

A bare `create_task` whose reference is dropped can be garbage collected mid-flight, and
its exception vanishes. `TaskGroup` guarantees both completion and exception propagation.

**Every external call has an explicit timeout.** No exceptions:

```python
async with asyncio.timeout(operator.deadline_ms / 1000):
    return await self._execute(operator)
```

A call without a timeout has an infinite timeout, and infinite timeouts are how a slow
dependency becomes a total outage.

## 4. Errors

Two categories, handled differently:

**Expected failures** — part of the domain. Returned as values:

```python
class BudgetExceeded(BaseModel):
    required_tokens: TokenCount
    available_tokens: TokenCount
    binding_constraint: Literal["tokens", "latency_ms", "compute_units"]

async def allocate(...) -> Result[Allocation, BudgetExceeded]: ...
```

**Unexpected failures** — bugs or infrastructure faults. Raised:

```python
class MnemosError(Exception):
    """Root. Every raised exception derives from this."""

class InfrastructureError(MnemosError): ...
class VectorIndexUnavailable(InfrastructureError): ...
```

A budget that cannot be satisfied is a normal outcome of a legitimate request; making it
an exception means every caller either handles it in a `try` or crashes. A dead database
is not a normal outcome and should propagate loudly.

**Never swallow an exception.** `except Exception: pass` is banned by lint. If a failure
is genuinely tolerable, it must be *recorded*:

```python
except OperatorTimeout as exc:
    bundle.degradations.append(
        DegradationEvent(
            operator_id=op.id, reason="deadline_exceeded",
            deadline_ms=op.deadline_ms, elapsed_ms=exc.elapsed_ms,
            fallback=op.fallback, impact=op.describe_impact(),
        )
    )
    logger.warning("operator.degraded", operator_id=op.id, reason="deadline_exceeded")
    return op.fallback_result()
```

Degradation is visible in the response, in the logs, and in the trace. A silent fallback
is a lie told to the caller.

**Error messages have two audiences.** The client gets a stable, non-leaking Problem
Detail; the log gets the diagnostic truth. Never leak an internal message, a stack
trace, a SQL fragment, or a file path across the API boundary.

## 5. Dependency injection

Constructor injection into use cases. FastAPI `Depends` only at the entrypoint layer.

```python
class WriteClaim:
    def __init__(
        self,
        repository: MemoryRepository,     # a Protocol, not a concrete class
        events: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._repository = repository
        self._events = events
        self._clock = clock
        self._ids = ids

    async def execute(self, cmd: WriteClaimCommand) -> Result[Claim, ClaimConflict]:
        ...
```

**Never call `datetime.now()` or `uuid4()` directly in application or domain code.** Both
come from injected ports. Bitemporal logic is defined entirely in terms of time, and
content-addressed digests must be reproducible — neither is testable if the code reaches
for a global clock. This is not purism; it is the difference between a deterministic test
suite and a flaky one.

The composition root is a single module. It is the only place that names concrete
adapters:

```python
def build_container(settings: Settings) -> Container:
    match settings.vector_backend:
        case VectorBackend.PGVECTOR: vector_index = PgVectorIndex(...)
        case VectorBackend.QDRANT:   vector_index = QdrantIndex(...)
    ...
```

## 6. Data access

**Repositories return domain models, never ORM rows.** An ORM object escaping the
adapter layer carries a lazy-loading session with it, and the resulting `MissingGreenlet`
appears far from its cause.

**Every query filters on `org_id` explicitly**, even though RLS also enforces it.
Defense in depth: RLS catches what review misses, and the explicit filter lets the
planner use the composite index.

**No N+1.** Batch or join. Integration tests assert query counts:

```python
async def test_bundle_load_is_single_query(query_counter):
    await store.load_bundle_with_items(digest)
    assert query_counter.count == 1
```

**Transaction boundaries live in the application layer**, never in repositories. A
repository that commits cannot participate in a larger unit of work — and claim
arbitration plus outbox insertion must be atomic.

## 7. Configuration

Pydantic `BaseSettings`, validated at startup, fail-fast:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MNEMOS_", env_file=".env")

    database_url: PostgresDsn
    model_tier: ModelTier = ModelTier.CPU_STANDARD
    default_token_budget: TokenCount = 8000
    rerank_margin_threshold: float = Field(default=0.05, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_tier_consistency(self) -> Self: ...
```

**No magic numbers anywhere.** `0.05`, `60`, `1536`, `0.87` in a function body are all
bugs waiting for someone to ask "why that value?" and find no answer. Every tunable is a
named setting with a default and a documented rationale.

**Secrets are never in code, never in defaults, never logged.** `SecretStr` for
in-memory handling; a `SecretResolver` port for retrieval. `.env.example` contains keys
with empty values, never real ones.

## 8. Logging and telemetry

structlog, JSON, contextvars-bound:

```python
logger.info(
    "context.compiled",
    bundle_digest=digest.hex(),
    tokens_consumed=bundle.tokens_consumed,
    operators_degraded=len(bundle.degradations),
    binding_constraint=report.binding_constraint,
)
```

- **Event names are `noun.verb_past`**, stable, and greppable. Never interpolate values
  into the message string — that makes aggregation impossible.
- `org_id`, `principal_id`, `request_id`, `trace_id` are bound once by middleware and
  appear on every subsequent line automatically.
- **Never log**: secrets, tokens, raw prompts containing user data, PII, full SQL with
  literals. A redacting processor runs on every record as a backstop, but the primary
  control is not logging it in the first place.
- Log levels: `DEBUG` development only · `INFO` state changes · `WARNING` degradation ·
  `ERROR` needs a human · `CRITICAL` data integrity at risk.

## 9. Testing

| Layer | Speed | Dependencies | Coverage gate |
|---|---|---|---|
| Unit | < 10 ms | none | 90% on `domain/` |
| Integration | < 2 s | testcontainers | 80% on `adapters/` |
| E2E | < 60 s | full compose | critical paths only |
| Contract | fast | schema only | 100% of endpoints |
| Performance | slow | full stack | nightly, not per-PR |

**Property-based tests for every pure policy function.** These are the functions where
example-based tests give false confidence:

```python
@given(
    initial=st.floats(0.0, 1.0),
    elapsed=st.floats(0.0, 365 * 24 * 3600),
    tau=st.floats(3600.0, 3.15e7),
)
def test_decay_is_monotonic_and_bounded(initial: float, elapsed: float, tau: float):
    result = apply_decay(initial, elapsed, tau)
    assert 0.0 <= result <= initial
    assert apply_decay(initial, elapsed * 2, tau) <= result
```

**Mandatory test cases** — these are the ones that catch real defects in this system:

1. **Bitemporal**: overlapping validity for the same `(subject, predicate, scope)` on a
   `semantic` claim raises; the same overlap on an `episodic` claim does not.
2. **RLS**: a session bound to org A reads zero rows written by org B, including through
   a deliberately org-unfiltered query.
3. **ACL pushdown recall**: with 90% of a corpus inaccessible, pushdown returns the
   accessible top-k; post-filtering (the banned approach) returns fewer. Asserted as a
   recall inequality, so the regression is caught if someone "optimizes" it later.
4. **SQL safety**: DML nested inside a CTE, inside a `UNION`, and inside a subquery is
   rejected; unparseable SQL is rejected fail-closed rather than passed through.
5. **Trust tier**: a tool call motivated by tier-5 content is denied, and the denial
   names the offending source.
6. **Budget**: assembled tokens never exceed the budget, across randomized section
   configurations (Hypothesis).
7. **Determinism**: compiling the same request twice with pinned versions yields an
   identical digest.
8. **Idempotency**: a replayed event is processed exactly once.

**No mocking of code you own.** Mock at the port boundary using in-memory fakes; use
real Postgres via testcontainers for adapters. A mocked SQLAlchemy session tests the
mock, and the assertion that the code "called `execute` once" survives any refactor
including a broken one.

## 10. Documentation in code

Docstrings on every public function, in Google style — but they explain **why**, not
what:

```python
def should_rerank(scores: Sequence[float], threshold: float) -> bool:
    """Decide whether cross-encoder reranking is worth its cost.

    Reranking only changes the outcome when the retriever is uncertain — that is,
    when the top-k scores are tightly clustered. When the margin between rank 1 and
    rank k is wide, the ordering is already confident and reranking spends ~400ms on
    CPU to reproduce it.

    Args:
        scores: Fused scores, descending.
        threshold: Minimum margin below which reranking fires. Tuned per org;
            see Settings.rerank_margin_threshold.

    Returns:
        True if reranking is expected to change the ordering.
    """
```

A docstring restating the signature is noise. A docstring explaining a non-obvious
decision is the highest-density documentation in the repository.

## 11. Commits and PRs

Conventional Commits, scoped by feature:

```
feat(context): add Lagrangian budget allocator with section floors
fix(memory): prevent supersession of tombstoned claims
perf(retrieval): push ACL predicate into HNSW scan
```

Every PR: passes all gates, updates docs when behaviour changes, adds an ADR for
architectural decisions, and includes a migration with a tested downgrade when the schema
changes.

**A PR that changes assembled context must update the golden bundle fixtures in the same
commit** — with the diff visible in review. That diff is the review artifact that
matters; without it, a context regression is invisible until someone notices the answers
got worse.
