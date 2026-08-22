"""C4 invariants proved against the migrated, RLS-forced Postgres schema."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import asyncpg
import pytest

import mnemos.platform.models  # noqa: F401 -- load the complete mapped graph
from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.ids import SequentialIdGenerator, uuid7
from mnemos.core.types import MemoryKind, OperatorKind, TrustTier
from mnemos.features.chat.domain import ChatMessageId, ChatSessionId
from mnemos.features.context.adapters.repository import SqlContextRepository
from mnemos.features.context.application.compiler import compile_context
from mnemos.features.context.domain import (
    AttachBundleCommand,
    ContextCandidate,
    PersistContextCommand,
)
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.domain import HeuristicTokenizer
from mnemos.features.memory.adapters.repository import SqlMemoryRepository
from mnemos.features.memory.application import MemoryService
from mnemos.features.observability.adapters.repository import SqlAuditRepository
from mnemos.platform.db import Database

from .conftest import Postgres


async def _seed_identity(postgres: Postgres) -> tuple[OrgId, OrgId, UserId, UserId]:
    org_a, org_b = OrgId(uuid7()), OrgId(uuid7())
    user_a, user_b = UserId(uuid7()), UserId(uuid7())
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        for org_id, slug in ((org_a, "context-a"), (org_b, "context-b")):
            await conn.execute(
                "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)",
                org_id,
                f"{slug}-{org_id}",
                slug,
            )
        for user_id, org_id, email in (
            (user_a, org_a, "context-a@example.test"),
            (user_b, org_b, "context-b@example.test"),
        ):
            await conn.execute(
                "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, 'Owner')",
                user_id,
                org_id,
                email,
            )
    finally:
        await conn.close()
    return org_a, org_b, user_a, user_b


@pytest.mark.asyncio
async def test_memory_supersession_preserves_both_clocks_acl_and_dag(postgres: Postgres) -> None:
    org_a, org_b, user_a, _ = await _seed_identity(postgres)
    database = Database(Settings(database_url=postgres.app_url, env="test"))
    clock = FrozenClock(datetime(2026, 1, 10, 9, tzinfo=UTC))
    service = MemoryService(
        repository=SqlMemoryRepository(database, SequentialIdGenerator("memory-c4")),
        clock=clock,
    )
    valid_from = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        first = await service.create(
            org_id=org_a,
            user_id=user_a,
            subject_kind="person",
            subject_ref="employee:ada",
            subject_name="Ada",
            predicate="home_hub",
            object_text="London",
            kind=MemoryKind.FACT,
            scope={},
            valid_from=valid_from,
            valid_to=None,
            confidence=0.9,
        )
        clock.advance(days=5)
        second = await service.create(
            org_id=org_a,
            user_id=user_a,
            subject_kind="person",
            subject_ref="employee:ada",
            subject_name="Ada",
            predicate="home_hub",
            object_text="Berlin",
            kind=MemoryKind.FACT,
            scope={},
            valid_from=valid_from,
            valid_to=None,
            confidence=1.0,
            supersede_id=first.claim.id,
        )
        assert second.superseded == (first.claim.id,)

        now = await service.history(org_id=org_a, include_retracted=True)
        assert [claim.object_text for claim in now.claims] == ["Berlin", "London"]
        assert now.claims[1].retracted_at == clock.now()
        assert now.claims[1].valid_from == valid_from
        assert [(edge.source_id, edge.target_id) for edge in now.edges] == [
            (second.claim.id, first.claim.id)
        ]

        before_replacement = await service.history(
            org_id=org_a,
            as_of=valid_from,
            believed_at=clock.now().replace(day=12),
        )
        assert [claim.object_text for claim in before_replacement.claims] == ["London"]
        after_replacement = await service.history(
            org_id=org_a,
            as_of=valid_from,
            believed_at=clock.now(),
        )
        assert [claim.object_text for claim in after_replacement.claims] == ["Berlin"]
        assert (await service.history(org_id=org_b)).claims == ()

        tag_id = uuid7()
        owner = await asyncpg.connect(postgres.owner_dsn)
        try:
            await owner.execute(
                "INSERT INTO tag (id, org_id, slug, name) VALUES ($1, $2, 'finance', 'Finance')",
                tag_id,
                org_a,
            )
            await owner.execute(
                "UPDATE memory SET acl_tag_ids = ARRAY[$1]::uuid[] WHERE id = $2",
                tag_id,
                second.claim.id,
            )
            with pytest.raises(asyncpg.ExclusionViolationError):
                async with owner.transaction():
                    await owner.execute(
                        """
                        INSERT INTO memory (
                            id, org_id, subject_id, predicate, object_text, kind,
                            status, scope, scope_hash, valid_range, confidence,
                            trust_tier, source_kind, created_by
                        )
                        SELECT $1, org_id, subject_id, predicate, 'Paris', kind,
                               'active', scope, scope_hash, valid_range, 1, 20,
                               'test', created_by
                          FROM memory WHERE id = $2
                        """,
                        uuid7(),
                        second.claim.id,
                    )
            with pytest.raises(asyncpg.CheckViolationError, match="supersession cycle"):
                async with owner.transaction():
                    await owner.execute(
                        "INSERT INTO memory_edge (id, org_id, src_id, dst_id, kind) VALUES ($1, $2, $3, $4, 'supersedes')",
                        uuid7(),
                        org_a,
                        first.claim.id,
                        second.claim.id,
                    )
        finally:
            await owner.close()

        assert (await service.history(org_id=org_a, caller_tags=())).claims[0].id == first.claim.id
        authorized = await service.history(org_id=org_a, caller_tags=("finance",))
        assert {claim.id for claim in authorized.claims} == {first.claim.id, second.claim.id}
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_supersede_and_retract_are_each_a_durable_audit_row(postgres: Postgres) -> None:
    """`C3` deliverable 5. A plain `create()` (no `supersede_id`) is routine
    authoring and is deliberately not audited here — only the bitemporal
    mutations TRACKER §5 names are."""
    org_a, _, user_a, _ = await _seed_identity(postgres)
    database = Database(Settings(database_url=postgres.app_url, env="test"))
    clock = FrozenClock(datetime(2026, 1, 10, 9, tzinfo=UTC))
    audit_repository = SqlAuditRepository(database, SequentialIdGenerator("audit-c3"))
    service = MemoryService(
        repository=SqlMemoryRepository(database, SequentialIdGenerator("memory-c3-audit")),
        clock=clock,
        audit=audit_repository,
    )
    try:
        first = await service.create(
            org_id=org_a,
            user_id=user_a,
            subject_kind="person",
            subject_ref="employee:ada",
            subject_name="Ada",
            predicate="home_hub",
            object_text="London",
            kind=MemoryKind.FACT,
            scope={},
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=None,
            confidence=0.9,
        )
        assert list(await audit_repository.list_events(org_id=org_a, limit=10)) == []

        second = await service.create(
            org_id=org_a,
            user_id=user_a,
            subject_kind="person",
            subject_ref="employee:ada",
            subject_name="Ada",
            predicate="home_hub",
            object_text="Berlin",
            kind=MemoryKind.FACT,
            scope={},
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=None,
            confidence=1.0,
            supersede_id=first.claim.id,
        )
        await service.retract(org_id=org_a, user_id=user_a, memory_id=second.claim.id)

        events = await audit_repository.list_events(org_id=org_a, limit=10)
        actions = [e.action for e in events]
        assert actions == ["memory.retract", "memory.supersede"], "newest first"
        assert all(e.outcome == "allow" for e in events)
        assert all(e.actor_id == user_a for e in events)
        supersede_event = next(e for e in events if e.action == "memory.supersede")
        assert supersede_event.resource_id == str(second.claim.id)
        retract_event = next(e for e in events if e.action == "memory.retract")
        assert retract_event.resource_id == str(second.claim.id)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_bundle_is_budget_checked_persisted_attached_and_owner_scoped(
    postgres: Postgres,
) -> None:
    org_a, _, user_a, _ = await _seed_identity(postgres)
    peer = UserId(uuid7())
    session_id, message_id = ChatSessionId(uuid7()), ChatMessageId(uuid7())
    owner = await asyncpg.connect(postgres.owner_dsn)
    try:
        await owner.execute(
            "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, 'peer@example.test', 'Peer')",
            peer,
            org_a,
        )
        await owner.execute(
            "INSERT INTO chat_session (id, org_id, user_id, title) VALUES ($1, $2, $3, 'C4')",
            session_id,
            org_a,
            user_a,
        )
        await owner.execute(
            "INSERT INTO chat_message (id, org_id, session_id, ordinal, role, content, flow) VALUES ($1, $2, $3, 0, 'assistant', 'Berlin', 'rag')",
            message_id,
            org_a,
            session_id,
        )
    finally:
        await owner.close()

    tokenizer = HeuristicTokenizer()
    compiled = compile_context(
        query="Where is Ada based?",
        system_prompt="Answer only from context.",
        candidates=[
            ContextCandidate(
                key="doc:berlin",
                section="documents",
                operator=OperatorKind.VECTOR,
                operator_id="hybrid",
                text="Ada's current home hub is Berlin.",
                tokens=tokenizer.count("Ada's current home hub is Berlin."),
                raw_score=0.9,
                rrf_score=0.02,
                trust_tier=TrustTier.RETRIEVED,
                source_kind="document",
                source_ref="handbook-current",
            )
        ],
        token_budget=120,
        tokenizer=tokenizer,
        utility_decay_tau=8.0,
        operator_actuals={"hybrid": {"returned": 1, "acl": "inside_scan"}},
    )
    assert compiled.tokens_consumed <= compiled.token_budget

    database = Database(Settings(database_url=postgres.app_url, env="test"))
    repository = SqlContextRepository(database, SequentialIdGenerator("context-c4"))
    try:
        bundle_id = await repository.persist(
            PersistContextCommand(
                org_id=org_a,
                user_id=user_a,
                session_id=session_id,
                flow="rag",
                query="Where is Ada based?",
                deadline_ms=250,
                compile_ms=3,
                embedder="hashing-384",
                tokenizer="HeuristicTokenizer",
                compiled=compiled,
                operators={"hybrid": {"returned": 1}},
            )
        )
        duplicate_id = await repository.persist(
            PersistContextCommand(
                org_id=org_a,
                user_id=user_a,
                session_id=session_id,
                flow="rag",
                query="Where is Ada based?",
                deadline_ms=250,
                compile_ms=3,
                embedder="hashing-384",
                tokenizer="HeuristicTokenizer",
                compiled=compiled,
                operators={"hybrid": {"returned": 1}},
            )
        )
        assert duplicate_id == bundle_id
        await repository.attach(
            AttachBundleCommand(org_id=org_a, message_id=message_id, bundle_id=bundle_id)
        )
        summary = await repository.get_for_message(
            org_id=org_a, user_id=user_a, message_id=message_id
        )
        assert summary is not None
        assert summary.digest == compiled.digest
        assert summary.tokens_consumed == compiled.tokens_consumed
        assert summary.admitted[0].acl_rule == "scan-time ACL predicate"
        assert (
            await repository.get_for_message(org_id=org_a, user_id=peer, message_id=message_id)
            is None
        )

        direct = await asyncpg.connect(postgres.owner_dsn)
        try:
            assert (
                await direct.fetchval("SELECT count(*) FROM context_plan WHERE org_id = $1", org_a)
                == 1
            )
            with pytest.raises(asyncpg.CheckViolationError):
                await direct.execute(
                    """
                    INSERT INTO context_bundle (
                        id, org_id, digest, flow, token_budget, tokens_consumed,
                        compiled_prompt, embedder, tokenizer, compile_ms
                    ) VALUES ($1, $2, $3, 'rag', 10, 11, 'bad', 'hashing', 'test', 0)
                    """,
                    uuid7(),
                    org_a,
                    hashlib.sha256(b"invalid-budget").hexdigest(),
                )
        finally:
            await direct.close()
    finally:
        await database.dispose()
