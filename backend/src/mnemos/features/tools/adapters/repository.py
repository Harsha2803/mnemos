"""Postgres repository for the existing MCP tables.

Every statement carries an explicit ``org_id`` predicate and also runs under
the tenant GUC, so an application mistake and an RLS mistake must coincide
before a row can cross organisations.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mnemos.core.ids import IdGenerator
from mnemos.core.types import InvocationStatus, JsonValue, TrustTier
from mnemos.features.context.adapters.models import BundleItem
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.knowledge.adapters.models import Document
from mnemos.features.tools.adapters.models import (
    McpCredential,
    McpGrant,
    McpInvocation,
    McpServer,
    McpTool,
)
from mnemos.features.tools.domain import (
    McpCredentialState,
    McpGrantId,
    McpGrantRecord,
    McpInvocationId,
    McpInvocationRecord,
    McpServerId,
    McpServerRecord,
    McpToolId,
    McpToolRecord,
)
from mnemos.platform.db import Database


def _server(row: McpServer) -> McpServerRecord:
    return McpServerRecord(
        id=McpServerId(row.id),
        org_id=OrgId(row.org_id),
        slug=row.slug,
        name=row.name,
        description=row.description,
        endpoint=row.endpoint,
        is_enabled=row.is_enabled,
        min_trust_tier=TrustTier(row.min_trust_tier),
        requires_approval=row.requires_approval,
        last_discovered_at=row.last_discovered_at,
        health_status=row.health_status,
    )


def _tool(row: McpTool) -> McpToolRecord:
    return McpToolRecord(
        id=McpToolId(row.id),
        org_id=OrgId(row.org_id),
        server_id=McpServerId(row.server_id),
        name=row.name,
        description=row.description,
        input_schema=cast(dict[str, JsonValue], row.input_schema),
        is_enabled=row.is_enabled,
        requires_approval=row.requires_approval,
        is_mutating=row.is_mutating,
    )


def _grant(row: McpGrant) -> McpGrantRecord:
    return McpGrantRecord(
        id=McpGrantId(row.id),
        org_id=OrgId(row.org_id),
        tool_id=McpToolId(row.tool_id),
        user_id=UserId(row.user_id),
        granted_by=UserId(row.granted_by) if row.granted_by is not None else None,
        auto_approve=row.auto_approve,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def _credential(row: McpCredential) -> McpCredentialState:
    return McpCredentialState(
        server_id=McpServerId(row.server_id),
        user_id=UserId(row.user_id),
        scheme=row.scheme,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
    )


def _invocation(row: McpInvocation, offending_source: str | None) -> McpInvocationRecord:
    return McpInvocationRecord(
        id=McpInvocationId(row.id),
        org_id=OrgId(row.org_id),
        tool_id=McpToolId(row.tool_id),
        user_id=UserId(row.user_id),
        message_id=str(row.message_id) if row.message_id is not None else None,
        arguments=cast(dict[str, JsonValue], row.arguments),
        status=InvocationStatus(row.status),
        caller_trust_tier=TrustTier(row.caller_trust_tier),
        denied_reason=row.denied_reason,
        offending_bundle_item_id=(
            str(row.offending_bundle_item_id)
            if row.offending_bundle_item_id is not None
            else None
        ),
        offending_source=offending_source,
        approved_by=UserId(row.approved_by) if row.approved_by is not None else None,
        approved_at=row.approved_at,
        result=cast(dict[str, JsonValue], row.result),
        duration_ms=row.duration_ms,
        error_code=row.error_code,
        created_at=row.created_at,
    )


async def _load_invocation(
    session: AsyncSession, *, org_id: OrgId, invocation_id: McpInvocationId
) -> McpInvocationRecord | None:
    result = await session.execute(
        select(McpInvocation, Document.title)
        .outerjoin(BundleItem, BundleItem.id == McpInvocation.offending_bundle_item_id)
        .outerjoin(Document, Document.id == BundleItem.document_id)
        .where(McpInvocation.org_id == org_id, McpInvocation.id == invocation_id)
    )
    found = result.one_or_none()
    return _invocation(found[0], found[1]) if found is not None else None


class SqlToolRepository:
    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def create_server(
        self,
        *,
        org_id: OrgId,
        slug: str,
        name: str,
        description: str | None,
        endpoint: str,
        min_trust_tier: TrustTier,
        requires_approval: bool,
    ) -> McpServerRecord:
        async with self._db.session(org_id=org_id) as session:
            row = McpServer(
                id=self._ids.new(),
                org_id=org_id,
                slug=slug,
                name=name,
                description=description,
                transport="http",
                endpoint=endpoint,
                min_trust_tier=int(min_trust_tier),
                requires_approval=requires_approval,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _server(row)

    async def list_servers(self, *, org_id: OrgId) -> Sequence[McpServerRecord]:
        async with self._db.session(org_id=org_id) as session:
            rows = (
                await session.scalars(
                    select(McpServer)
                    .where(McpServer.org_id == org_id)
                    .order_by(McpServer.slug)
                )
            ).all()
        return [_server(row) for row in rows]

    async def get_server(
        self, *, org_id: OrgId, server_id: McpServerId
    ) -> McpServerRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(McpServer).where(
                    McpServer.org_id == org_id, McpServer.id == server_id
                )
            )
        return _server(row) if row is not None else None

    async def replace_discovered_tools(
        self,
        *,
        org_id: OrgId,
        server_id: McpServerId,
        tools: Sequence[McpToolRecord],
        discovered_at: datetime,
    ) -> Sequence[McpToolRecord]:
        names = [tool.name for tool in tools]
        async with self._db.session(org_id=org_id) as session:
            if names:
                await session.execute(
                    delete(McpTool).where(
                        McpTool.org_id == org_id,
                        McpTool.server_id == server_id,
                        McpTool.name.not_in(names),
                    )
                )
            else:
                await session.execute(
                    delete(McpTool).where(
                        McpTool.org_id == org_id, McpTool.server_id == server_id
                    )
                )
            for tool in tools:
                statement = insert(McpTool).values(
                    id=tool.id,
                    org_id=org_id,
                    server_id=server_id,
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    is_enabled=tool.is_enabled,
                    requires_approval=tool.requires_approval,
                    is_mutating=tool.is_mutating,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        constraint="uq_mcp_tool_server_id_name",
                        set_={
                            "description": statement.excluded.description,
                            "input_schema": statement.excluded.input_schema,
                            "updated_at": func.now(),
                        },
                    )
                )
            await session.execute(
                update(McpServer)
                .where(McpServer.org_id == org_id, McpServer.id == server_id)
                .values(last_discovered_at=discovered_at, health_status="healthy")
            )
            rows = (
                await session.scalars(
                    select(McpTool)
                    .where(McpTool.org_id == org_id, McpTool.server_id == server_id)
                    .order_by(McpTool.name)
                )
            ).all()
        return [_tool(row) for row in rows]

    async def list_tools(
        self, *, org_id: OrgId, server_id: McpServerId | None = None
    ) -> Sequence[McpToolRecord]:
        statement = select(McpTool).where(McpTool.org_id == org_id)
        if server_id is not None:
            statement = statement.where(McpTool.server_id == server_id)
        async with self._db.session(org_id=org_id) as session:
            rows = (await session.scalars(statement.order_by(McpTool.name))).all()
        return [_tool(row) for row in rows]

    async def get_tool(
        self, *, org_id: OrgId, tool_id: McpToolId
    ) -> McpToolRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(McpTool).where(McpTool.org_id == org_id, McpTool.id == tool_id)
            )
        return _tool(row) if row is not None else None

    async def put_credential(
        self,
        *,
        org_id: OrgId,
        server_id: McpServerId,
        user_id: UserId,
        scheme: str,
        secret_encrypted: bytes,
        expires_at: datetime | None,
    ) -> McpCredentialState:
        statement = insert(McpCredential).values(
            id=self._ids.new(),
            org_id=org_id,
            server_id=server_id,
            user_id=user_id,
            scheme=scheme,
            secret_encrypted=secret_encrypted,
            expires_at=expires_at,
        )
        async with self._db.session(org_id=org_id) as session:
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_mcp_credential_server_id_user_id",
                    set_={
                        "scheme": statement.excluded.scheme,
                        "secret_encrypted": statement.excluded.secret_encrypted,
                        "expires_at": statement.excluded.expires_at,
                        "updated_at": func.now(),
                    },
                )
            )
            row = await session.scalar(
                select(McpCredential).where(
                    McpCredential.org_id == org_id,
                    McpCredential.server_id == server_id,
                    McpCredential.user_id == user_id,
                )
            )
            if row is None:  # pragma: no cover - the upsert above guarantees it
                raise RuntimeError("credential upsert returned no row")
            return _credential(row)

    async def get_credential_state(
        self, *, org_id: OrgId, server_id: McpServerId, user_id: UserId
    ) -> McpCredentialState | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(McpCredential).where(
                    McpCredential.org_id == org_id,
                    McpCredential.server_id == server_id,
                    McpCredential.user_id == user_id,
                )
            )
        return _credential(row) if row is not None else None

    async def get_encrypted_credential(
        self, *, org_id: OrgId, server_id: McpServerId, user_id: UserId
    ) -> tuple[str, bytes] | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(McpCredential).where(
                    McpCredential.org_id == org_id,
                    McpCredential.server_id == server_id,
                    McpCredential.user_id == user_id,
                )
            )
        return (row.scheme, row.secret_encrypted) if row is not None else None

    async def put_grant(
        self,
        *,
        org_id: OrgId,
        tool_id: McpToolId,
        user_id: UserId,
        granted_by: UserId,
        auto_approve: bool,
        expires_at: datetime | None,
    ) -> McpGrantRecord:
        statement = insert(McpGrant).values(
            id=self._ids.new(),
            org_id=org_id,
            tool_id=tool_id,
            user_id=user_id,
            granted_by=granted_by,
            auto_approve=auto_approve,
            expires_at=expires_at,
            revoked_at=None,
        )
        async with self._db.session(org_id=org_id) as session:
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_mcp_grant_tool_id_user_id",
                    set_={
                        "granted_by": statement.excluded.granted_by,
                        "auto_approve": statement.excluded.auto_approve,
                        "expires_at": statement.excluded.expires_at,
                        "revoked_at": None,
                        "updated_at": func.now(),
                    },
                )
            )
            row = await session.scalar(
                select(McpGrant).where(
                    McpGrant.org_id == org_id,
                    McpGrant.tool_id == tool_id,
                    McpGrant.user_id == user_id,
                )
            )
            if row is None:  # pragma: no cover - the upsert above guarantees it
                raise RuntimeError("grant upsert returned no row")
            return _grant(row)

    async def get_grant(
        self, *, org_id: OrgId, tool_id: McpToolId, user_id: UserId, at: datetime
    ) -> McpGrantRecord | None:
        async with self._db.session(org_id=org_id) as session:
            row = await session.scalar(
                select(McpGrant).where(
                    McpGrant.org_id == org_id,
                    McpGrant.tool_id == tool_id,
                    McpGrant.user_id == user_id,
                    McpGrant.revoked_at.is_(None),
                    (McpGrant.expires_at.is_(None) | (McpGrant.expires_at > at)),
                )
            )
        return _grant(row) if row is not None else None

    async def create_invocation(
        self,
        *,
        org_id: OrgId,
        tool_id: McpToolId,
        user_id: UserId,
        arguments: dict[str, JsonValue],
        status: InvocationStatus,
        caller_trust_tier: TrustTier,
        denied_reason: str | None,
        offending_bundle_item_id: str | None,
    ) -> McpInvocationRecord:
        invocation_id = McpInvocationId(self._ids.new())
        async with self._db.session(org_id=org_id) as session:
            session.add(
                McpInvocation(
                    id=invocation_id,
                    org_id=org_id,
                    tool_id=tool_id,
                    user_id=user_id,
                    arguments=arguments,
                    status=status.value,
                    caller_trust_tier=int(caller_trust_tier),
                    denied_reason=denied_reason,
                    offending_bundle_item_id=(
                        uuid.UUID(offending_bundle_item_id)
                        if offending_bundle_item_id is not None
                        else None
                    ),
                )
            )
            await session.flush()
            row = await _load_invocation(
                session, org_id=org_id, invocation_id=invocation_id
            )
            if row is None:  # pragma: no cover - the insert above guarantees it
                raise RuntimeError("invocation insert returned no row")
            return row

    async def get_invocation(
        self, *, org_id: OrgId, invocation_id: McpInvocationId
    ) -> McpInvocationRecord | None:
        async with self._db.session(org_id=org_id) as session:
            return await _load_invocation(
                session, org_id=org_id, invocation_id=invocation_id
            )

    async def transition_invocation(
        self,
        *,
        org_id: OrgId,
        invocation_id: McpInvocationId,
        expected: InvocationStatus,
        status: InvocationStatus,
        approved_by: UserId | None = None,
        approved_at: datetime | None = None,
        result: dict[str, JsonValue] | None = None,
        duration_ms: int | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> McpInvocationRecord | None:
        values: dict[str, object] = {"status": status.value}
        if approved_by is not None:
            values["approved_by"] = approved_by
        if approved_at is not None:
            values["approved_at"] = approved_at
        if result is not None:
            values["result"] = result
        if duration_ms is not None:
            values["duration_ms"] = duration_ms
        if error_code is not None:
            values["error_code"] = error_code
        if error_detail is not None:
            values["error_detail"] = error_detail
        async with self._db.session(org_id=org_id) as session:
            updated = await session.execute(
                update(McpInvocation)
                .where(
                    McpInvocation.org_id == org_id,
                    McpInvocation.id == invocation_id,
                    McpInvocation.status == expected.value,
                )
                .values(**values)
                .returning(McpInvocation.id)
            )
            if updated.scalar_one_or_none() is None:
                return None
            return await _load_invocation(
                session, org_id=org_id, invocation_id=invocation_id
            )

    async def list_invocations(
        self, *, org_id: OrgId, user_id: UserId
    ) -> Sequence[McpInvocationRecord]:
        async with self._db.session(org_id=org_id) as session:
            result = await session.execute(
                select(McpInvocation, Document.title)
                .outerjoin(BundleItem, BundleItem.id == McpInvocation.offending_bundle_item_id)
                .outerjoin(Document, Document.id == BundleItem.document_id)
                .where(
                    McpInvocation.org_id == org_id,
                    McpInvocation.user_id == user_id,
                )
                .order_by(McpInvocation.created_at.desc())
            )
            rows = result.all()
        return [_invocation(row, source) for row, source in rows]

