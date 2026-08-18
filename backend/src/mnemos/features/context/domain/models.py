"""Typed context-plan, candidate, decision, and persisted-bundle records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NewType
from uuid import UUID

from mnemos.core.types import JsonValue, OperatorKind, TrustTier
from mnemos.features.chat.domain import ChatMessageId, ChatSessionId
from mnemos.features.identity.domain import OrgId, UserId

ContextPlanId = NewType("ContextPlanId", UUID)
ContextBundleId = NewType("ContextBundleId", UUID)
BundleItemId = NewType("BundleItemId", UUID)


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    key: str
    section: str
    operator: OperatorKind
    operator_id: str
    text: str
    tokens: int
    raw_score: float
    rrf_score: float
    trust_tier: TrustTier
    source_kind: str
    source_ref: str
    chunk_id: UUID | None = None
    memory_id: UUID | None = None
    document_id: UUID | None = None
    document_title: str | None = None
    acl_rule: str = "public_within_org"
    utility: float = 0.0
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextRejection:
    key: str
    section: str
    source_kind: str
    source_ref: str
    reason: str
    tokens: int
    utility: float
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledContext:
    digest: str
    prompt: str
    token_budget: int
    tokens_consumed: int
    admitted: tuple[ContextCandidate, ...]
    rejections: tuple[ContextRejection, ...]
    budget_report: dict[str, JsonValue]
    explain: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ContextBundleSummary:
    id: ContextBundleId
    digest: str
    flow: str
    token_budget: int
    tokens_consumed: int
    compiled_prompt: str
    budget_report: dict[str, JsonValue]
    explain: dict[str, JsonValue]
    admitted: tuple[BundleItemRecord, ...]
    rejections: tuple[ContextRejection, ...]
    lineage: tuple[BundleLineageRecord, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BundleItemRecord:
    id: BundleItemId
    position: int
    section: str
    operator: OperatorKind
    text: str
    tokens: int
    raw_score: float
    rrf_score: float
    utility: float
    density: float
    trust_tier: TrustTier
    source_kind: str
    source_ref: str
    document_title: str | None
    acl_rule: str
    memory_id: UUID | None


@dataclass(frozen=True, slots=True)
class BundleLineageRecord:
    source_id: UUID
    target_id: UUID
    kind: str
    rationale: str | None


@dataclass(frozen=True, slots=True)
class PersistContextCommand:
    org_id: OrgId
    user_id: UserId
    session_id: ChatSessionId
    flow: str
    query: str
    deadline_ms: int
    compile_ms: int
    embedder: str
    tokenizer: str
    compiled: CompiledContext
    operators: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class AttachBundleCommand:
    org_id: OrgId
    message_id: ChatMessageId
    bundle_id: ContextBundleId
