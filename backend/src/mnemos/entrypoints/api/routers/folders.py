"""Folder routes: create, list, rename/reorder, delete.

Authenticated by doing nothing, same as `chat.py` — nothing here declares a
guard or appears in `public_route_paths`. Permission `chat:write` covers every
mutation and `chat:read` covers listing, already granted to `analyst` and
`user` — a folder organizes a caller's own sessions, the same authority level
as renaming one of them.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from mnemos.core.errors import NotFoundError
from mnemos.entrypoints.api.security import require_caller
from mnemos.features.chat.application.folders import FolderService
from mnemos.features.chat.domain import FolderId, FolderRecord
from mnemos.features.identity.application.principals import AuthenticatedCaller

router = APIRouter(prefix="/chat/folders", tags=["chat"])


class FolderResponse(BaseModel):
    id: str
    name: str
    position: int
    session_count: int
    created_at: str
    updated_at: str


class FolderListResponse(BaseModel):
    folders: list[FolderResponse]


class CreateFolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class UpdateFolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    position: int | None = Field(default=None, ge=0)


def _folder_response(record: FolderRecord) -> FolderResponse:
    return FolderResponse(
        id=str(record.id),
        name=record.name,
        position=record.position,
        session_count=record.session_count,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def _service(request: Request) -> FolderService:
    service = getattr(request.app.state, "folder_service", None)
    if not isinstance(service, FolderService):  # pragma: no cover - the lifespan sets it
        msg = "folder service is not configured"
        raise RuntimeError(msg)
    return service


def _parse_folder_id(raw: str) -> FolderId:
    try:
        return FolderId(uuid.UUID(raw))
    except ValueError as exc:
        raise NotFoundError(f"folder {raw} not found") from exc


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: CreateFolderRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[FolderService, Depends(_service)],
) -> FolderResponse:
    record = await service.create_folder(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        name=body.name,
    )
    return _folder_response(record)


@router.get("")
async def list_folders(
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[FolderService, Depends(_service)],
) -> FolderListResponse:
    folders = await service.list_folders(
        org_id=caller.principal.org_id, user_id=caller.principal.principal_id
    )
    return FolderListResponse(folders=[_folder_response(f) for f in folders])


@router.patch("/{folder_id}")
async def update_folder(
    folder_id: str,
    body: UpdateFolderRequest,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[FolderService, Depends(_service)],
) -> FolderResponse:
    record = await service.rename_folder(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        folder_id=_parse_folder_id(folder_id),
        name=body.name,
        position=body.position,
    )
    return _folder_response(record)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require_caller)],
    service: Annotated[FolderService, Depends(_service)],
) -> None:
    await service.delete_folder(
        org_id=caller.principal.org_id,
        user_id=caller.principal.principal_id,
        folder_id=_parse_folder_id(folder_id),
    )
