"""Persistence boundary for bitemporal memory."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from mnemos.core.types import MemoryKind, TrustTier
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.memory.domain import MemoryHistory, MemoryId, MemoryWriteResult


class MemoryRepository(Protocol):
    async def write(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        subject_kind: str,
        subject_ref: str,
        subject_name: str,
        predicate: str,
        object_text: str,
        kind: MemoryKind,
        scope: dict[str, str],
        valid_from: datetime,
        valid_to: datetime,
        confidence: float,
        trust_tier: TrustTier,
        source_kind: str,
        source_ref: str | None,
        recorded_at: datetime,
        supersede_id: MemoryId | None = None,
    ) -> MemoryWriteResult: ...

    async def retract(self, *, org_id: OrgId, memory_id: MemoryId, at: datetime) -> bool: ...

    async def history(
        self,
        *,
        org_id: OrgId,
        caller_tags: Sequence[str],
        subject_ref: str | None,
        as_of: datetime | None,
        believed_at: datetime | None,
        include_retracted: bool,
    ) -> MemoryHistory: ...
