"""Register MCP servers and cache their discovered catalog."""

from __future__ import annotations

from collections.abc import Sequence

from mnemos.core.clock import Clock
from mnemos.core.ids import IdGenerator
from mnemos.core.types import TrustTier
from mnemos.features.identity.domain import OrgId, UserId
from mnemos.features.tools.adapters.crypto import ToolCredentialCipher
from mnemos.features.tools.adapters.mcp_http import StreamableHttpMcpClient
from mnemos.features.tools.application.ports import ToolRepository
from mnemos.features.tools.domain import (
    McpCredentialState,
    McpServerId,
    McpServerRecord,
    McpToolId,
    McpToolRecord,
)


class ToolCatalogService:
    def __init__(
        self,
        *,
        repository: ToolRepository,
        client: StreamableHttpMcpClient,
        cipher: ToolCredentialCipher,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._repository = repository
        self._client = client
        self._cipher = cipher
        self._clock = clock
        self._ids = ids

    async def register_server(
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
        await self._client.validate_endpoint(endpoint)
        return await self._repository.create_server(
            org_id=org_id,
            slug=slug,
            name=name,
            description=description,
            endpoint=endpoint,
            min_trust_tier=min_trust_tier,
            requires_approval=requires_approval,
        )

    async def discover(
        self, *, org_id: OrgId, user_id: UserId, server_id: McpServerId
    ) -> Sequence[McpToolRecord]:
        server = await self._repository.get_server(org_id=org_id, server_id=server_id)
        if server is None or not server.is_enabled:
            return ()
        stored = await self._repository.get_encrypted_credential(
            org_id=org_id, server_id=server_id, user_id=user_id
        )
        credential = (
            (stored[0], self._cipher.decrypt(stored[1])) if stored is not None else None
        )
        discovered = await self._client.list_tools(
            endpoint=server.endpoint, credential=credential
        )
        records = [
            McpToolRecord(
                id=McpToolId(self._ids.new()),
                org_id=org_id,
                server_id=server.id,
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                is_enabled=True,
                requires_approval=False,
                is_mutating=tool.is_mutating,
            )
            for tool in discovered
        ]
        return await self._repository.replace_discovered_tools(
            org_id=org_id,
            server_id=server_id,
            tools=records,
            discovered_at=self._clock.now(),
        )

    async def list_servers(self, *, org_id: OrgId) -> Sequence[McpServerRecord]:
        return await self._repository.list_servers(org_id=org_id)

    async def list_tools(
        self, *, org_id: OrgId, server_id: McpServerId | None = None
    ) -> Sequence[McpToolRecord]:
        return await self._repository.list_tools(org_id=org_id, server_id=server_id)

    async def save_credential(
        self,
        *,
        org_id: OrgId,
        user_id: UserId,
        server_id: McpServerId,
        scheme: str,
        secret: str,
    ) -> None:
        await self._repository.put_credential(
            org_id=org_id,
            server_id=server_id,
            user_id=user_id,
            scheme=scheme,
            secret_encrypted=self._cipher.encrypt(secret),
            expires_at=None,
        )

    async def credential_state(
        self, *, org_id: OrgId, user_id: UserId, server_id: McpServerId
    ) -> McpCredentialState | None:
        return await self._repository.get_credential_state(
            org_id=org_id, server_id=server_id, user_id=user_id
        )
