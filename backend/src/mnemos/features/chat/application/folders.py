"""Folder use cases: create, list, rename/reorder, delete.

A sibling service to `ChatService` rather than a growing method list on it —
the same shape `features/tools/` uses for `ToolCatalogService` and
`ToolInvocationService`, two services sharing one repository."""

from __future__ import annotations

from collections.abc import Sequence

from mnemos.core.errors import NotFoundError
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.domain import FolderId, FolderRecord
from mnemos.features.identity.domain import OrgId, UserId


class FolderService:
    def __init__(self, *, repository: ChatRepository) -> None:
        self._repository = repository

    async def create_folder(self, *, org_id: OrgId, user_id: UserId, name: str) -> FolderRecord:
        return await self._repository.create_folder(org_id=org_id, user_id=user_id, name=name)

    async def list_folders(self, *, org_id: OrgId, user_id: UserId) -> Sequence[FolderRecord]:
        return await self._repository.list_folders(org_id=org_id, user_id=user_id)

    async def rename_folder(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        folder_id: FolderId,
        name: str | None = None,
        position: int | None = None,
    ) -> FolderRecord:
        await self._owned_folder(org_id=org_id, user_id=user_id, folder_id=folder_id)
        renamed = await self._repository.rename_folder(
            org_id=org_id, folder_id=folder_id, name=name, position=position
        )
        if renamed is None:  # pragma: no cover - vanished between the two calls
            raise NotFoundError(f"folder {folder_id} not found")
        return renamed

    async def delete_folder(self, *, org_id: OrgId, user_id: UserId, folder_id: FolderId) -> None:
        await self._owned_folder(org_id=org_id, user_id=user_id, folder_id=folder_id)
        await self._repository.delete_folder(org_id=org_id, folder_id=folder_id)

    async def _owned_folder(
        self, *, org_id: OrgId, user_id: UserId, folder_id: FolderId
    ) -> FolderRecord:
        """404, never 403 — the same convention `ChatService._owned_session`
        documents for sessions."""
        folder = await self._repository.get_folder(
            org_id=org_id, user_id=user_id, folder_id=folder_id
        )
        if folder is None:
            raise NotFoundError(f"folder {folder_id} not found")
        return folder
