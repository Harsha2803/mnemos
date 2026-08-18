"""Reproducible Postgres benchmark for governed context compilation.

The corpus and gold labels remain owned by the frozen ``_v1.dataset`` module so
they cannot drift while the execution path changes underneath them.  No legacy
store, retriever, compiler, or SQLite module is imported here.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import anyio
import asyncpg
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects import postgresql

import mnemos.platform.models  # noqa: F401 -- configure the complete ORM graph
from mnemos._v1.dataset import (
    DOCUMENTS,
    MEMORY_QUESTION,
    OUTDATED_MARKERS,
    QUESTIONS,
    SEED_CLAIMS,
    STALE_VALUE,
    SUPERSEDED_DOCUMENTS,
    Question,
)
from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.ids import SequentialIdGenerator
from mnemos.core.types import (
    ConnectorKind,
    DocumentStatus,
    MemoryKind,
    OperatorKind,
    TrustTier,
)
from mnemos.features.context.application import compile_context
from mnemos.features.context.domain import ContextCandidate
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.adapters.models import Chunk, ChunkEmbedding, Document
from mnemos.features.knowledge.adapters.retrieval import SqlRetriever
from mnemos.features.knowledge.domain import (
    HashingEmbedder,
    HeuristicTokenizer,
    chunk_text,
    reciprocal_rank_fusion,
)
from mnemos.features.memory.adapters.repository import SqlMemoryRepository
from mnemos.features.memory.application import MemoryService
from mnemos.features.memory.domain import MemoryRecord
from mnemos.platform.db import Database

SYSTEM_PROMPT = (
    "You are Northwind's internal assistant. Answer only from the provided context. "
    "If the context does not contain the answer, say so."
)
DEFAULT_BUDGETS = (800, 1500, 3000)
REPRODUCTION_COMMAND = "make bench"
POSTGRES_IMAGE = "pgvector/pgvector:pg16"
APP_PASSWORD = "benchmark-app-role"
BACKEND_ROOT = Path(__file__).resolve().parents[4]
_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "mnemos-postgres-benchmark-v1")
_WORDS = re.compile(r"[a-z0-9]+")
_WS = re.compile(r"\s+")


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(_UUID_NAMESPACE, name)


ORG_ID = OrgId(_id("org"))
USER_ID = UserId(_id("user"))
PAYROLL_TAG_ID = _id("tag:payroll")


@dataclass(frozen=True, slots=True)
class DatabaseUrls:
    owner_url: str
    owner_dsn: str
    app_url: str


@dataclass(slots=True)
class ArmResult:
    name: str
    answer_retention: float
    budget_overrun_rate: float
    mean_tokens: float
    p95_tokens: int
    duplicate_waste: float
    acl_leak_rate: float
    stale_fact_rate: float
    outdated_doc_rate: float
    provenance: float
    mean_latency_ms: float
    p95_latency_ms: float
    detail: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PromptResult:
    prompt: str
    tokens_consumed: int
    latency_ms: float
    truncated: bool
    manifest_items: int = 0
    digest: str | None = None
    evicted: int = 0


def _norm(text: str) -> str:
    return _WS.sub(" ", text)


def _contains(haystack: str, needle: str) -> bool:
    return _norm(needle) in _norm(haystack)


def _duplicate_waste(prompt: str, window: int = 12) -> float:
    tokens = _WORDS.findall(prompt.lower())
    if len(tokens) <= window:
        return 0.0
    seen: set[tuple[str, ...]] = set()
    duplicated = 0
    index = 0
    while index <= len(tokens) - window:
        gram = tuple(tokens[index : index + window])
        if gram in seen:
            duplicated += window
            index += window
        else:
            seen.add(gram)
            index += 1
    return duplicated / len(tokens)


def _acl_leaked(prompt: str) -> bool:
    markers = (
        "118,000 to 146,000 EUR",
        "149,000 to 188,000 EUR",
        "location factor for the Berlin hub is 1.00",
        "Equity refresh for E6",
    )
    return any(_contains(prompt, marker) for marker in markers)


def _p95(values: Sequence[float]) -> int | float:
    if not values:
        return 0
    ordered = sorted(values)
    value = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _hard_truncate(text: str, tokenizer: HeuristicTokenizer, budget: int) -> str:
    if tokenizer.count(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if tokenizer.count(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _acl_clause(caller_tag_ids: Sequence[uuid.UUID]) -> Any:
    public = ChunkEmbedding.acl_tag_ids == []
    if not caller_tag_ids:
        return public
    return or_(
        public,
        ChunkEmbedding.acl_tag_ids.overlap(
            postgresql.array(caller_tag_ids).cast(postgresql.ARRAY(postgresql.UUID(as_uuid=True)))
        ),
    )


class BenchmarkCorpus:
    """The benchmark-only baseline and production governed retrieval path."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.embedder = HashingEmbedder()
        self.tokenizer = HeuristicTokenizer()
        self.retriever = SqlRetriever(database)
        self.memory = MemoryService(
            repository=SqlMemoryRepository(
                database, SequentialIdGenerator("benchmark-memory-reads")
            ),
            clock=FrozenClock(datetime(2026, 3, 1, tzinfo=UTC)),
        )

    async def naive_prompt(
        self,
        *,
        query: str,
        budget: int,
        variant: Literal["naive", "naive_postfilter", "naive_prefilter"],
        k: int = 12,
    ) -> PromptResult:
        """Preserve the frozen baseline, including its deliberately unfair arms.

        ``naive_prefilter`` is the fair control: ACL is in the SQL scan.
        ``naive_postfilter`` is retained and explicitly labelled unfair because
        denied rows consume rank positions before Python removes them.
        """
        started = time.perf_counter()
        vector = self.embedder.encode([query])[0]
        distance = ChunkEmbedding.embedding.cosine_distance(vector)
        query_stmt = (
            select(Chunk.text, ChunkEmbedding.acl_tag_ids)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .where(Chunk.org_id == ORG_ID)
            .order_by(distance.asc(), Chunk.id.asc())
            .limit(k * 2)
        )
        if variant == "naive_prefilter":
            query_stmt = query_stmt.where(_acl_clause(()))
        async with self.database.session(org_id=ORG_ID) as session:
            rows = list((await session.execute(query_stmt)).all())
        if variant == "naive_postfilter":
            rows = [row for row in rows if not row.acl_tag_ids]
        rows = rows[:k]

        history = await self.memory.history(
            org_id=ORG_ID,
            subject_ref="user-alex",
            include_retracted=True,
        )
        selected_memory = self._rank_memory(query, history.claims, k=6)
        parts = [SYSTEM_PROMPT]
        parts.extend(
            f"{claim.predicate.replace('_', ' ')}: {claim.object_text}" for claim in selected_memory
        )
        parts.extend(row.text for row in rows)
        parts.append(query)
        raw = "\n\n".join(parts)
        truncated = self.tokenizer.count(raw) > budget
        prompt = _hard_truncate(raw, self.tokenizer, budget)
        return PromptResult(
            prompt=prompt,
            tokens_consumed=self.tokenizer.count(prompt),
            latency_ms=(time.perf_counter() - started) * 1000,
            truncated=truncated,
        )

    async def compiled_prompt(self, *, query: str, budget: int, k: int = 12) -> PromptResult:
        started = time.perf_counter()
        vector = self.embedder.encode([query])[0]
        vector_rows, lexical_rows = await asyncio.gather(
            self.retriever.vector_search(
                org_id=ORG_ID, caller_tag_ids=(), query_vector=vector, k=k
            ),
            self.retriever.lexical_search(org_id=ORG_ID, caller_tag_ids=(), query_text=query, k=k),
        )
        fused = reciprocal_rank_fusion([vector_rows, lexical_rows])
        candidates = [
            ContextCandidate(
                key=f"chunk:{item.chunk.chunk_id}",
                section="documents",
                operator=OperatorKind.VECTOR,
                operator_id="postgres_hybrid",
                text=item.chunk.text,
                tokens=item.chunk.token_count,
                raw_score=item.chunk.score,
                rrf_score=item.rrf_score,
                trust_tier=TrustTier.RETRIEVED,
                source_kind="document",
                source_ref=str(item.chunk.document_id),
                chunk_id=item.chunk.chunk_id,
                document_id=item.chunk.document_id,
                document_title=item.chunk.document_title,
                acl_rule="scan-time ACL predicate",
            )
            for item in fused
        ]
        history = await self.memory.history(
            org_id=ORG_ID,
            subject_ref="user-alex",
            include_retracted=False,
        )
        for rank, claim in enumerate(self._rank_memory(query, history.claims, k=6)):
            text = f"{claim.predicate.replace('_', ' ')}: {claim.object_text}"
            candidates.append(
                ContextCandidate(
                    key=f"memory:{claim.id}",
                    section="memory",
                    operator=OperatorKind.MEMORY,
                    operator_id="postgres_memory",
                    text=text,
                    tokens=self.tokenizer.count(text),
                    raw_score=1.0 / (rank + 1),
                    rrf_score=1.0 / (61 + rank),
                    trust_tier=claim.trust_tier,
                    source_kind=claim.source_kind,
                    source_ref=claim.source_ref or str(claim.id),
                    memory_id=claim.id,
                    acl_rule="scan-time ACL predicate",
                    metadata={
                        "subject_ref": claim.subject.external_ref,
                        "predicate": claim.predicate,
                        "recorded_at": claim.recorded_at.isoformat(),
                    },
                )
            )
        compiled = compile_context(
            query=query,
            system_prompt=SYSTEM_PROMPT,
            candidates=candidates,
            token_budget=budget,
            tokenizer=self.tokenizer,
            utility_decay_tau=6.0,
            operator_actuals={
                "postgres_hybrid": {
                    "vector_returned": len(vector_rows),
                    "lexical_returned": len(lexical_rows),
                    "acl": "inside_scan",
                    "currency": "inside_scan",
                },
                "postgres_memory": {
                    "returned": len(history.claims),
                    "acl": "inside_scan",
                    "belief_time": "inside_scan",
                },
            },
        )
        return PromptResult(
            prompt=compiled.prompt,
            tokens_consumed=compiled.tokens_consumed,
            latency_ms=(time.perf_counter() - started) * 1000,
            truncated=False,
            manifest_items=len(compiled.admitted),
            digest=compiled.digest,
            evicted=len(compiled.rejections),
        )

    def _rank_memory(
        self, query: str, claims: Sequence[MemoryRecord], *, k: int
    ) -> list[MemoryRecord]:
        if not claims:
            return []
        texts = [f"{claim.predicate} {claim.object_text}" for claim in claims]
        query_vector = self.embedder.encode([query])[0]
        vectors = self.embedder.encode(texts)
        scores = vectors @ query_vector
        order = sorted(
            range(len(claims)),
            key=lambda index: (-float(scores[index]), str(claims[index].id)),
        )
        return [claims[index] for index in order[:k]]


async def _score_arm(
    corpus: BenchmarkCorpus,
    questions: Sequence[Question],
    budget: int,
    name: str,
) -> ArmResult:
    prompts: list[PromptResult] = []
    for question in questions:
        if name == "mnemos_compiled":
            prompts.append(await corpus.compiled_prompt(query=question.query, budget=budget))
        else:
            prompts.append(
                await corpus.naive_prompt(
                    query=question.query,
                    budget=budget,
                    variant=name,  # type: ignore[arg-type]
                )
            )

    detail: list[dict[str, Any]] = []
    for question, result in zip(questions, prompts, strict=True):
        detail.append(
            {
                "qid": question.qid,
                "retained": _contains(result.prompt, question.answer_key),
                "tokens": result.tokens_consumed,
                "over_budget": result.tokens_consumed > budget,
                "acl_leak": _acl_leaked(result.prompt),
                "stale": _contains(result.prompt, STALE_VALUE),
                "outdated_doc": any(
                    _contains(result.prompt, marker) for marker in OUTDATED_MARKERS
                ),
                "truncated": result.truncated,
                "manifest_items": result.manifest_items,
                "evicted": result.evicted,
                "digest": result.digest,
            }
        )
    size = len(detail)
    token_counts = [result.tokens_consumed for result in prompts]
    latencies = [result.latency_ms for result in prompts]
    return ArmResult(
        name=name,
        answer_retention=sum(item["retained"] for item in detail) / size,
        budget_overrun_rate=sum(item["over_budget"] for item in detail) / size,
        mean_tokens=statistics.mean(token_counts),
        p95_tokens=int(_p95(token_counts)),
        duplicate_waste=statistics.mean(_duplicate_waste(result.prompt) for result in prompts),
        acl_leak_rate=sum(item["acl_leak"] for item in detail) / size,
        stale_fact_rate=sum(item["stale"] for item in detail) / size,
        outdated_doc_rate=sum(item["outdated_doc"] for item in detail) / size,
        provenance=(
            sum(result.manifest_items > 0 for result in prompts) / size
            if name == "mnemos_compiled"
            else 0.0
        ),
        mean_latency_ms=statistics.mean(latencies),
        p95_latency_ms=float(_p95(latencies)),
        detail=detail,
    )


async def run_benchmark(urls: DatabaseUrls, budgets: Sequence[int]) -> dict[str, Any]:
    database = Database(
        Settings(database_url=urls.app_url, env="test", app_database_password=APP_PASSWORD)
    )
    try:
        await _seed_corpus(urls.owner_url, database)
        corpus = BenchmarkCorpus(database)
        questions = [*QUESTIONS, MEMORY_QUESTION]
        async with database.session(org_id=ORG_ID) as session:
            chunks = int((await session.scalar(select(func.count(Chunk.id)))) or 0)
            corpus_tokens = int(
                (await session.scalar(select(func.coalesce(func.sum(Chunk.token_count), 0)))) or 0
            )
        results: dict[str, Any] = {
            "meta": {
                "backend": "postgresql",
                "postgres_image": POSTGRES_IMAGE,
                "embedder": corpus.embedder.name,
                "documents": len(DOCUMENTS) + len(SUPERSEDED_DOCUMENTS),
                "chunks": chunks,
                "corpus_tokens": corpus_tokens,
                "questions": len(questions),
                "memory_claims": len(SEED_CLAIMS),
                "budgets": list(budgets),
                "reproduction_command": REPRODUCTION_COMMAND,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "arms": {
                    "naive": "unfair: no authorization",
                    "naive_postfilter": "unfair: authorization after top-k",
                    "naive_prefilter": "fair control: authorization inside SQL scan",
                    "mnemos_compiled": "governed: ACL and currency inside Postgres scans",
                },
            },
            "by_budget": {},
        }
        for budget in budgets:
            arms = [
                await _score_arm(corpus, questions, budget, "naive"),
                await _score_arm(corpus, questions, budget, "naive_postfilter"),
                await _score_arm(corpus, questions, budget, "naive_prefilter"),
                await _score_arm(corpus, questions, budget, "mnemos_compiled"),
            ]
            results["by_budget"][str(budget)] = {arm.name: asdict(arm) for arm in arms}
        return results
    finally:
        await database.dispose()


async def _seed_corpus(owner_url: str, app_database: Database) -> None:
    owner_database = Database(Settings(database_url=owner_url, env="test"))
    embedder = HashingEmbedder()
    tokenizer = HeuristicTokenizer()
    try:
        async with owner_database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO org (id, slug, name)
                    VALUES (:org, 'northwind-benchmark', 'Northwind Robotics')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"org": ORG_ID},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO app_user (id, org_id, email, display_name)
                    VALUES (:id, :org, 'alex@northwind.example', 'Alex')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": USER_ID, "org": ORG_ID},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO tag (id, org_id, slug, name)
                    VALUES (:id, :org, 'payroll', 'Payroll')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": PAYROLL_TAG_ID, "org": ORG_ID},
            )

        current_ids = {doc.key: _id(f"document:{doc.key}") for doc in DOCUMENTS}
        all_docs = [*DOCUMENTS, *SUPERSEDED_DOCUMENTS]
        async with owner_database.session() as session:
            for doc in all_docs:
                old = doc in SUPERSEDED_DOCUMENTS
                lineage = doc.key.removesuffix("_2024")
                document_id = _id(f"document:{doc.key}")
                acl = [PAYROLL_TAG_ID] if doc.key == "payroll" else []
                document = Document(
                    id=document_id,
                    org_id=ORG_ID,
                    title=doc.title,
                    media_type="text/plain",
                    byte_size=len(doc.body.encode()),
                    content_sha256=hashlib.sha256(doc.body.encode()).hexdigest(),
                    source_kind=ConnectorKind.HTTP.value,
                    source_uri=f"internal://{doc.key}",
                    status=(DocumentStatus.SUPERSEDED.value if old else DocumentStatus.READY.value),
                    lineage_key=lineage,
                    revision=1 if old else 2,
                    superseded_by=current_ids.get(lineage) if old else None,
                    acl_tag_ids=acl,
                    trust_tier=int(TrustTier.RETRIEVED),
                    doc_metadata={"benchmark_key": doc.key},
                    uploaded_by=USER_ID,
                )
                session.add(document)
                # These mappings deliberately have no ORM relationships, so the
                # unit-of-work cannot infer that documents precede their chunks.
                await session.flush()
                for raw in chunk_text(doc.body, tokenizer):
                    chunk_id = _id(f"chunk:{doc.key}:{raw.ordinal}")
                    session.add(
                        Chunk(
                            id=chunk_id,
                            org_id=ORG_ID,
                            document_id=document_id,
                            ordinal=raw.ordinal,
                            text=raw.content,
                            token_count=raw.token_count,
                            start_char=raw.char_start,
                            end_char=raw.char_end,
                            page_number=raw.page,
                            heading_path=[raw.heading] if raw.heading else [],
                            content_sha256=hashlib.sha256(raw.content.encode()).hexdigest(),
                        )
                    )
                    session.add(
                        ChunkEmbedding(
                            id=_id(f"embedding:{doc.key}:{raw.ordinal}"),
                            org_id=ORG_ID,
                            chunk_id=chunk_id,
                            document_id=document_id,
                            model=embedder.name,
                            dim=embedder.dim,
                            embedding=embedder.encode([raw.content])[0],
                            is_current=not old,
                            acl_tag_ids=acl,
                            trust_tier=int(TrustTier.RETRIEVED),
                        )
                    )

        repository = SqlMemoryRepository(
            app_database, SequentialIdGenerator("benchmark-memory-seed")
        )
        deployment_claim = None
        for seed in SEED_CLAIMS:
            old_kind = seed.kind.value
            kind = MemoryKind.OBSERVATION if old_kind == "episodic" else MemoryKind.FACT
            service = MemoryService(
                repository=repository,
                clock=FrozenClock(seed.valid_from),
            )
            result = await service.create(
                org_id=ORG_ID,
                user_id=USER_ID,
                subject_kind="person",
                subject_ref="user-alex",
                subject_name="Alex",
                predicate=seed.predicate,
                object_text=seed.object_text,
                kind=kind,
                scope={},
                valid_from=seed.valid_from,
                valid_to=None,
                confidence=seed.salience,
                source_kind="benchmark",
                source_ref=f"seed:{seed.predicate}",
                supersede_id=(
                    deployment_claim
                    if seed.predicate == "deployment_region" and deployment_claim is not None
                    else None
                ),
            )
            if seed.predicate == "deployment_region":
                deployment_claim = result.claim.id
    finally:
        await owner_database.dispose()


async def _prepare_database(urls: DatabaseUrls) -> None:
    conn = await asyncpg.connect(urls.owner_dsn)
    try:
        for extension in ("vector", "pg_trgm", "btree_gist", "citext", '"uuid-ossp"'):
            await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    finally:
        await conn.close()
    env = {
        **os.environ,
        "MNEMOS_ENV": "test",
        "MNEMOS_DATABASE_URL": urls.owner_url,
        "MNEMOS_APP_DATABASE_PASSWORD": APP_PASSWORD,
    }
    await anyio.to_thread.run_sync(
        lambda: subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=env,
            check=True,
        )
    )


@asynccontextmanager
async def _postgres() -> AsyncIterator[DatabaseUrls]:
    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer(
        POSTGRES_IMAGE,
        username="mnemos",
        password="mnemos",
        dbname="mnemos",
        driver=None,
    )
    with container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(5432))
        urls = DatabaseUrls(
            owner_url=f"postgresql+asyncpg://mnemos:mnemos@{host}:{port}/mnemos",
            owner_dsn=f"postgresql://mnemos:mnemos@{host}:{port}/mnemos",
            app_url=f"postgresql+asyncpg://mnemos_app:{APP_PASSWORD}@{host}:{port}/mnemos",
        )
        await _prepare_database(urls)
        yield urls


def format_table(results: dict[str, Any]) -> str:
    meta = results["meta"]
    lines = [
        (
            f"postgres: {meta['postgres_image']} | corpus: {meta['documents']} docs / "
            f"{meta['chunks']} chunks / {meta['corpus_tokens']} tokens | "
            f"{meta['questions']} questions | {meta['memory_claims']} memory claims | "
            f"embedder: {meta['embedder']}"
        )
    ]
    for budget, arms in results["by_budget"].items():
        lines.extend(("", f"=== token budget: {budget} ==="))
        header = (
            f"{'arm':<20} {'answer':>7} {'over':>6} {'tok':>7} {'dup':>7} "
            f"{'acl':>6} {'stale':>7} {'olddoc':>7} {'prov':>6} {'ms':>8}"
        )
        lines.extend((header, "-" * len(header)))
        for name, arm in arms.items():
            lines.append(
                f"{name:<20} {arm['answer_retention'] * 100:>6.1f}% "
                f"{arm['budget_overrun_rate'] * 100:>5.0f}% "
                f"{arm['mean_tokens']:>7.0f} "
                f"{arm['duplicate_waste'] * 100:>6.1f}% "
                f"{arm['acl_leak_rate'] * 100:>5.0f}% "
                f"{arm['stale_fact_rate'] * 100:>6.0f}% "
                f"{arm['outdated_doc_rate'] * 100:>6.0f}% "
                f"{arm['provenance'] * 100:>5.0f}% "
                f"{arm['mean_latency_ms']:>8.1f}"
            )
    return "\n".join(lines)


async def _async_main(args: argparse.Namespace) -> dict[str, Any]:
    budgets = [int(value) for value in args.budgets.split(",")]
    async with _postgres() as urls:
        return await run_benchmark(urls, budgets)


def main() -> None:
    parser = argparse.ArgumentParser(description="Postgres naive-vs-compiled benchmark")
    parser.add_argument("--budgets", default=",".join(map(str, DEFAULT_BUDGETS)))
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()
    results = asyncio.run(_async_main(args))
    print(format_table(results))
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
