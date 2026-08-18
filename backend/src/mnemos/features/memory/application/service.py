"""Bitemporal memory lifecycle without an overwrite operation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from mnemos.core.clock import END_OF_TIME, Clock
from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.core.types import MemoryKind, TrustTier
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.memory.application.ports import MemoryRepository
from mnemos.features.memory.domain import MemoryHistory, MemoryId, MemoryWriteResult


class MemoryService:
    def __init__(self, *, repository: MemoryRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def create(
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
        valid_from: datetime | None,
        valid_to: datetime | None,
        confidence: float,
        source_kind: str = "user",
        source_ref: str | None = None,
        supersede_id: MemoryId | None = None,
    ) -> MemoryWriteResult:
        start = valid_from or self._clock.now()
        end = valid_to or END_OF_TIME
        if end <= start:
            raise ValidationError("valid_to must be later than valid_from", field="valid_to")
        return await self._repository.write(
            org_id=org_id,
            user_id=user_id,
            subject_kind=subject_kind.strip(),
            subject_ref=subject_ref.strip(),
            subject_name=subject_name.strip(),
            predicate=predicate.strip(),
            object_text=object_text.strip(),
            kind=kind,
            scope=scope,
            valid_from=start,
            valid_to=end,
            confidence=confidence,
            trust_tier=TrustTier.USER,
            source_kind=source_kind,
            source_ref=source_ref,
            recorded_at=self._clock.now(),
            supersede_id=supersede_id,
        )

    async def retract(self, *, org_id: OrgId, memory_id: MemoryId) -> None:
        if not await self._repository.retract(
            org_id=org_id, memory_id=memory_id, at=self._clock.now()
        ):
            raise NotFoundError(f"memory {memory_id} not found")

    async def history(
        self,
        *,
        org_id: OrgId,
        caller_tags: Sequence[str] = (),
        subject_ref: str | None = None,
        as_of: datetime | None = None,
        believed_at: datetime | None = None,
        include_retracted: bool = True,
    ) -> MemoryHistory:
        return await self._repository.history(
            org_id=org_id,
            caller_tags=caller_tags,
            subject_ref=subject_ref,
            as_of=as_of,
            believed_at=believed_at,
            include_retracted=include_retracted,
        )
