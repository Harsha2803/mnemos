"""MCP wire safety: discovery, local validation, and bounded responses."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest

from mnemos.core.errors import UpstreamError, ValidationError
from mnemos.core.types import JsonValue
from mnemos.features.tools.adapters import mcp_http
from mnemos.features.tools.adapters.mcp_http import StreamableHttpMcpClient


async def _pinned(
    url: str, *, allowed_private_hosts: object = ()
) -> tuple[httpx.URL, str]:
    del allowed_private_hosts
    return httpx.URL(url).copy_with(host="203.0.113.10"), "tools.example.test"


def _client(handler: httpx.AsyncBaseTransport, *, cap: int = 10_000) -> StreamableHttpMcpClient:
    return StreamableHttpMcpClient(
        client=httpx.AsyncClient(transport=handler),
        timeout_s=1,
        response_max_bytes=cap,
    )


@pytest.mark.asyncio
async def test_discovers_and_classifies_a_read_only_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_http, "resolve_and_pin", _pinned)

    def respond(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if '"initialize"' in body:
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-1"},
                json={"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}},
            )
        assert request.headers["mcp-session-id"] == "session-1"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                                "required": ["message"],
                                "additionalProperties": False,
                            },
                            "annotations": {"readOnlyHint": True},
                        }
                    ]
                },
            },
        )

    transport = httpx.MockTransport(respond)
    client = _client(transport)
    tools = await client.list_tools(endpoint="https://tools.example.test/mcp", credential=None)
    await client._client.aclose()

    assert len(tools) == 1
    assert tools[0].name == "echo"
    assert tools[0].is_mutating is False


def test_arguments_are_rejected_before_dispatch() -> None:
    schema: Mapping[str, JsonValue] = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError, match="do not match"):
        mcp_http.validate_arguments(input_schema=schema, arguments={"message": 42})


@pytest.mark.asyncio
async def test_response_size_cap_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_http, "resolve_and_pin", _pinned)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"{" + (b"x" * 2_000) + b"}")
    )
    client = _client(transport, cap=1_024)

    with pytest.raises(UpstreamError, match="too much data"):
        await client.list_tools(endpoint="https://tools.example.test/mcp", credential=None)
    await client._client.aclose()


@pytest.mark.asyncio
async def test_redirect_is_never_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_http, "resolve_and_pin", _pinned)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})
    )
    client = _client(transport)

    with pytest.raises(UpstreamError, match="refused"):
        await client.list_tools(endpoint="https://tools.example.test/mcp", credential=None)
    await client._client.aclose()
