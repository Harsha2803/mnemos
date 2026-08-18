"""Typed identifiers for the MCP tool boundary."""

from __future__ import annotations

from typing import NewType
from uuid import UUID

McpServerId = NewType("McpServerId", UUID)
McpToolId = NewType("McpToolId", UUID)
McpGrantId = NewType("McpGrantId", UUID)
McpInvocationId = NewType("McpInvocationId", UUID)

