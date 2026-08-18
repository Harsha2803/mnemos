"""Persistence boundary for explainable context artifacts."""

from __future__ import annotations

from typing import Protocol

from mnemos.features.chat.domain import ChatMessageId
from mnemos.features.context.domain import (
    AttachBundleCommand,
    ContextBundleId,
    ContextBundleSummary,
    PersistContextCommand,
)
from mnemos.features.identity.domain import OrgId, UserId


class ContextRepository(Protocol):
    async def persist(self, command: PersistContextCommand) -> ContextBundleId: ...

    async def attach(self, command: AttachBundleCommand) -> None: ...

    async def get_for_message(
        self, *, org_id: OrgId, user_id: UserId, message_id: ChatMessageId
    ) -> ContextBundleSummary | None: ...
