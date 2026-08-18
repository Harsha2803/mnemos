"""Postgres persistence and replay reads for compiled context bundles."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from mnemos.core.ids import IdGenerator
from mnemos.core.types import JsonValue, OperatorKind, TrustTier
from mnemos.features.chat.adapters.models import ChatMessage, ChatSession
from mnemos.features.chat.domain import ChatMessageId
from mnemos.features.context.adapters.models import BundleItem, ContextBundle, ContextPlan
from mnemos.features.context.domain import (
    AttachBundleCommand,
    BundleItemId,
    BundleItemRecord,
    BundleLineageRecord,
    ContextBundleId,
    ContextBundleSummary,
    ContextRejection,
    PersistContextCommand,
)
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.adapters.models import Document
from mnemos.features.memory.adapters.models import MemoryEdge
from mnemos.platform.db import Database


class SqlContextRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def persist(self, command: PersistContextCommand) -> ContextBundleId:
        plan_id = self._ids.new()
        bundle_id = self._ids.new()
        report: dict[str, JsonValue] = {
            **command.compiled.budget_report,
            "explain": command.compiled.explain,
        }
        rejection_json = [
            {
                "key": item.key,
                "section": item.section,
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
                "reason": item.reason,
                "tokens": item.tokens,
                "utility": item.utility,
                "detail": item.detail,
            }
            for item in command.compiled.rejections
        ]
        section_budgets = cast(dict[str, JsonValue], report.get("sections", {}))

        async with self._db.session(org_id=command.org_id) as session:
            session.add(
                ContextPlan(
                    id=plan_id,
                    org_id=command.org_id,
                    query_text=command.query,
                    query_sha256=hashlib.sha256(command.query.encode()).hexdigest(),
                    total_budget=command.compiled.token_budget,
                    section_budgets=section_budgets,
                    operators=command.operators,
                    deadline_ms=command.deadline_ms,
                )
            )
            await session.flush()
            inserted = await session.scalar(
                insert(ContextBundle)
                .values(
                    id=bundle_id,
                    org_id=command.org_id,
                    plan_id=plan_id,
                    session_id=command.session_id,
                    digest=command.compiled.digest,
                    flow=command.flow,
                    token_budget=command.compiled.token_budget,
                    tokens_consumed=command.compiled.tokens_consumed,
                    budget_report=report,
                    rejections=rejection_json,
                    compiled_prompt=command.compiled.prompt,
                    embedder=command.embedder,
                    tokenizer=command.tokenizer,
                    compile_ms=command.compile_ms,
                )
                .on_conflict_do_nothing(constraint="uq_context_bundle_org_id_digest")
                .returning(ContextBundle.id)
            )
            if inserted is None:
                existing = await session.scalar(
                    select(ContextBundle.id).where(
                        ContextBundle.org_id == command.org_id,
                        ContextBundle.digest == command.compiled.digest,
                    )
                )
                if existing is None:  # pragma: no cover - conflict guarantees a row
                    raise RuntimeError("context bundle conflict returned no existing row")
                return ContextBundleId(existing)

            for position, item in enumerate(command.compiled.admitted):
                session.add(
                    BundleItem(
                        id=self._ids.new(),
                        org_id=command.org_id,
                        bundle_id=bundle_id,
                        position=position,
                        section=item.section,
                        operator=item.operator.value,
                        chunk_id=item.chunk_id,
                        memory_id=item.memory_id,
                        document_id=item.document_id,
                        text_snapshot=item.text,
                        tokens=item.tokens,
                        raw_score=item.raw_score,
                        rrf_score=item.rrf_score,
                        utility=item.utility,
                        density=item.utility / max(item.tokens, 1),
                        trust_tier=int(item.trust_tier),
                        acl_rule_id=None,
                    )
                )
        return ContextBundleId(bundle_id)

    async def attach(self, command: AttachBundleCommand) -> None:
        async with self._db.session(org_id=command.org_id) as session:
            changed = await session.scalar(
                update(ChatMessage)
                .where(
                    ChatMessage.org_id == command.org_id,
                    ChatMessage.id == command.message_id,
                )
                .values(bundle_id=command.bundle_id)
                .returning(ChatMessage.id)
            )
            if changed is None:
                raise RuntimeError("assistant message vanished before bundle attachment")

    async def get_for_message(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId
    ) -> ContextBundleSummary | None:
        async with self._db.session(org_id=org_id) as session:
            bundle = await session.scalar(
                select(ContextBundle)
                .join(ChatMessage, ChatMessage.bundle_id == ContextBundle.id)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(
                    ContextBundle.org_id == org_id,
                    ChatMessage.org_id == org_id,
                    ChatMessage.id == message_id,
                    ChatSession.org_id == org_id,
                    ChatSession.user_id == user_id,
                    ChatSession.deleted_at.is_(None),
                )
            )
            if bundle is None:
                return None
            item_rows = (
                await session.execute(
                    select(BundleItem, Document.title)
                    .outerjoin(Document, Document.id == BundleItem.document_id)
                    .where(BundleItem.org_id == org_id, BundleItem.bundle_id == bundle.id)
                    .order_by(BundleItem.position.asc())
                )
            ).all()
            memory_ids = [row.BundleItem.memory_id for row in item_rows if row.BundleItem.memory_id]
            edges: Sequence[MemoryEdge] = ()
            if memory_ids:
                edges = (
                    await session.scalars(
                        select(MemoryEdge).where(
                            MemoryEdge.org_id == org_id,
                            (MemoryEdge.src_id.in_(memory_ids) | MemoryEdge.dst_id.in_(memory_ids)),
                        )
                    )
                ).all()

        report = cast(dict[str, JsonValue], bundle.budget_report)
        explain_value = report.get("explain", {})
        explain = explain_value if isinstance(explain_value, dict) else {}
        return ContextBundleSummary(
            id=ContextBundleId(bundle.id),
            digest=bundle.digest,
            flow=bundle.flow,
            token_budget=bundle.token_budget,
            tokens_consumed=bundle.tokens_consumed,
            compiled_prompt=bundle.compiled_prompt,
            budget_report={key: value for key, value in report.items() if key != "explain"},
            explain=explain,
            admitted=tuple(_item_record(row.BundleItem, row.title) for row in item_rows),
            rejections=tuple(_rejection_record(item) for item in bundle.rejections),
            lineage=tuple(
                BundleLineageRecord(
                    source_id=edge.src_id,
                    target_id=edge.dst_id,
                    kind=edge.kind,
                    rationale=edge.rationale,
                )
                for edge in edges
            ),
            created_at=bundle.created_at,
        )


def _item_record(row: BundleItem, document_title: str | None) -> BundleItemRecord:
    if row.memory_id is not None:
        source_kind, source_ref = "memory", str(row.memory_id)
    elif row.chunk_id is not None:
        source_kind, source_ref = "document", str(row.chunk_id)
    elif row.operator == OperatorKind.HISTORY.value:
        source_kind, source_ref = "history", "conversation history"
    elif row.operator == OperatorKind.SQL.value:
        source_kind, source_ref = "sql", "SQL result"
    else:
        source_kind, source_ref = "tool", "tool input"
    return BundleItemRecord(
        id=BundleItemId(row.id),
        position=row.position,
        section=row.section,
        operator=OperatorKind(row.operator),
        text=row.text_snapshot,
        tokens=row.tokens,
        raw_score=row.raw_score,
        rrf_score=row.rrf_score,
        utility=row.utility,
        density=row.density,
        trust_tier=TrustTier(row.trust_tier),
        source_kind=source_kind,
        source_ref=source_ref,
        document_title=document_title,
        acl_rule="scan-time ACL predicate",
        memory_id=row.memory_id,
    )


def _rejection_record(value: dict[str, object]) -> ContextRejection:
    tokens = value.get("tokens", 0)
    utility = value.get("utility", 0.0)
    return ContextRejection(
        key=str(value.get("key", "unknown")),
        section=str(value.get("section", "unknown")),
        source_kind=str(value.get("source_kind", "unknown")),
        source_ref=str(value.get("source_ref", "unknown")),
        reason=str(value.get("reason", "unknown")),
        tokens=tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else 0,
        utility=(
            float(utility)
            if isinstance(utility, (int, float)) and not isinstance(utility, bool)
            else 0.0
        ),
        detail=str(value["detail"]) if value.get("detail") is not None else None,
    )
