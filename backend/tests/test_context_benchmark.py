"""Contract tests for C4's Postgres-only benchmark."""

from __future__ import annotations

import pytest

from mnemos.features.context.benchmark import DatabaseUrls, run_benchmark

from .conftest import Postgres


@pytest.mark.asyncio
async def test_postgres_benchmark_preserves_corpus_arms_and_governance(
    postgres: Postgres,
) -> None:
    results = await run_benchmark(
        DatabaseUrls(
            owner_url=postgres.owner_url,
            owner_dsn=postgres.owner_dsn,
            app_url=postgres.app_url,
        ),
        [800],
    )

    meta = results["meta"]
    assert meta["backend"] == "postgresql"
    assert meta["documents"] == 8
    assert meta["chunks"] == 56
    assert meta["corpus_tokens"] == 5387
    assert meta["questions"] == 23
    assert meta["memory_claims"] == 8
    assert meta["budgets"] == [800]
    assert meta["reproduction_command"] == "make bench"
    assert meta["arms"]["naive_prefilter"].startswith("fair control")
    assert meta["arms"]["naive_postfilter"].startswith("unfair")

    arms = results["by_budget"]["800"]
    assert set(arms) == {
        "naive",
        "naive_postfilter",
        "naive_prefilter",
        "mnemos_compiled",
    }
    compiled = arms["mnemos_compiled"]
    assert compiled["budget_overrun_rate"] == 0
    assert compiled["acl_leak_rate"] == 0
    assert compiled["stale_fact_rate"] == 0
    assert compiled["outdated_doc_rate"] == 0
    assert compiled["provenance"] == 1
    assert all(item["tokens"] <= 800 for item in compiled["detail"])
