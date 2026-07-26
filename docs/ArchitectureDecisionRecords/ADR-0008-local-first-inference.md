# ADR-0008 — Local-first inference; zero paid dependencies in the default path

**Status:** Accepted · **Date:** 2026-07-26

## Context

The project must run at zero monetary cost while remaining pluggable to hosted providers.
This is a hard constraint, not a preference.

The naive reading is that this is a limitation to work around. It is not — it changes
which designs are correct, and in every case examined it selected the better one.

## Decision

**Four independently routable capability roles, each with a free local default and a
config-only paid alternative.**

| Role | Free default | Paid alternative |
|---|---|---|
| `embedding` | `bge-small-en-v1.5` (384d), sentence-transformers, CPU | OpenAI · Cohere · Voyage |
| `rerank` | `bge-reranker-base` cross-encoder, CPU | Cohere Rerank |
| `generation` | Ollama · Qwen2.5-3B / Llama-3.2-3B | Any LiteLLM provider |
| `classification` | **No model** — embedding nearest-centroid over intent exemplars | Small hosted model |

Cost is denominated in provider-agnostic **`compute_units`**, normalized by a calibration
benchmark run at setup. `MNEMOS_MODEL_TIER` selects a coherent bundle (`cpu-minimal`,
`cpu-standard`, `gpu-8gb`, `hosted`) covering models, batch sizes, quantization, and
default budgets.

## Rationale

**The constraint forced three better decisions.**

*1 — Intent classification without a model.* On CPU, one generation call costs roughly
**300× an embedding call** (~3.5 s vs ~12 ms). Spending a generation call on intent
extraction is unaffordable, so the default became an embedding nearest-centroid classifier
over labelled exemplars. That is cheaper *and* more deterministic than an LLM classifier —
which matters because determinism is load-bearing for bundle reproducibility
([ADR-0001](ADR-0001-context-as-compiled-artifact.md)). A hosted-first design would likely
never have found this.

*2 — The budget allocator became load-bearing.* Under hosted inference the binding
constraint is almost always tokens, and a truncation rule would be adequate. Under local
inference the binding constraint is **latency**, which is a genuinely harder allocation
problem and the more interesting demonstration of why a cost-based optimizer is warranted.

*3 — The cost model started making non-trivial decisions.* The allocator rejects
abstractive compression on CPU essentially always (6 s for a token saving that is not
worth it), and begins accepting it on a GPU tier. **Same code, different decision, driven
by measured statistics.** That is a far better demonstration of a working optimizer than
any hardcoded heuristic.

**Pluggability is architectural, not aspirational.** LiteLLM already speaks Ollama,
HuggingFace TGI, vLLM, and every hosted API. The four roles are separate ports precisely so
a user can plug in a hosted embedding model while keeping local generation, or vice versa.
Adding a provider is an environment variable.

**`compute_units` keeps the ledger comparable.** Recording only wall-clock time would make
historical data incomparable the moment a hosted key is added. Recording only dollars would
make the free default's ledger uniformly zero and therefore useless for optimization. Both
columns exist; `compute_units` is what the allocator reads.

## Alternatives considered

**Hosted APIs with a spending cap.** Simpler, better quality, faster. Rejected: violates
the hard constraint, and makes the project unclonable — a reviewer without a key cannot run
it, which defeats the purpose of a public repository.

**Local only, no pluggability.** Simpler still. Rejected: the ability to swap providers by
configuration is one of the design's demonstrated properties, and removing it would discard
a genuine strength.

**A single `LLMProvider` port instead of four roles.** Rejected: embedding, reranking,
generation, and classification have different latency profiles, different failure modes,
and different optimal providers. One port would force them to share a routing policy that
suits none of them.

## Consequences

**Positive** — runs anywhere with no key; forced the better classification and allocation
designs; provider-agnostic accounting; degradation is graceful because local is always a
valid fallback target.

**Negative** — local model output quality is lower than frontier models, which most affects
Flow B (NL2SQL generation); first run must download several GB of models; CPU inference
requires thread-pool offload discipline everywhere, since one inline call blocks the event
loop for seconds.

**New threat introduced** ([ThreatModel T6](../ThreatModel.md#t6--model-supply-chain)):
running third-party model weights locally creates a supply-chain risk absent with hosted
APIs. Mitigated by `safetensors`-only loading (never pickle-based `.bin`), commit-pinned
model revisions, checksum verification, and loading models in a container with no
credential access. This is the honest cost of the choice, and it is accepted knowingly.

**Open question Q5** ([Roadmap §5](../Roadmap.md#5-open-questions)): if a 3B model cannot
generate correct SQL for non-trivial schemas, the correct response is to declare a minimum
model tier for that flow — not to quietly add a hosted fallback and break the guarantee.
