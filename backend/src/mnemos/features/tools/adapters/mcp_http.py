"""MCP streamable-HTTP client with a pinned, bounded egress path."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from mnemos.core.errors import UpstreamError, ValidationError
from mnemos.core.types import JsonValue
from mnemos.features.connectors.adapters.ssrf_guard import resolve_and_pin

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True, slots=True)
class DiscoveredMcpTool:
    name: str
    description: str | None
    input_schema: dict[str, JsonValue]
    is_mutating: bool


class StreamableHttpMcpClient:
    """One MCP request at a time; no planner, loop, or background session."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        timeout_s: float,
        response_max_bytes: int,
        allowed_private_hosts: Collection[str] = (),
    ) -> None:
        self._client = client
        self._timeout_s = timeout_s
        self._response_max_bytes = response_max_bytes
        self._allowed_private_hosts = frozenset(allowed_private_hosts)

    async def validate_endpoint(self, endpoint: str) -> None:
        """Resolve and pin now so registration rejects unsafe destinations."""
        await resolve_and_pin(endpoint, allowed_private_hosts=self._allowed_private_hosts)

    async def list_tools(
        self, *, endpoint: str, credential: tuple[str, str] | None
    ) -> Sequence[DiscoveredMcpTool]:
        session_id = await self._initialize(endpoint=endpoint, credential=credential)
        result, _ = await self._rpc(
            endpoint=endpoint,
            credential=credential,
            session_id=session_id,
            request_id=2,
            method="tools/list",
            params={},
        )
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise UpstreamError(
                "the MCP server returned an invalid response", reason="tools/list omitted tools"
            )
        tools: list[DiscoveredMcpTool] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                raise UpstreamError(
                    "the MCP server returned an invalid response",
                    reason="tools/list contained a non-object",
                )
            name = item.get("name")
            schema = item.get("inputSchema")
            description = item.get("description")
            annotations = item.get("annotations")
            if not isinstance(name, str) or not isinstance(schema, dict):
                raise UpstreamError(
                    "the MCP server returned an invalid response",
                    reason="a discovered tool omitted name or inputSchema",
                )
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise UpstreamError(
                    "the MCP server returned an invalid response",
                    reason=f"tool {name!r} supplied invalid JSON Schema: {exc.message}",
                ) from exc
            read_only = isinstance(annotations, dict) and annotations.get("readOnlyHint") is True
            tools.append(
                DiscoveredMcpTool(
                    name=name,
                    description=description if isinstance(description, str) else None,
                    input_schema=cast(dict[str, JsonValue], schema),
                    is_mutating=not read_only,
                )
            )
        return tools

    async def call_tool(
        self,
        *,
        endpoint: str,
        tool_name: str,
        input_schema: Mapping[str, JsonValue],
        arguments: Mapping[str, JsonValue],
        credential: tuple[str, str] | None,
    ) -> dict[str, JsonValue]:
        validate_arguments(input_schema=input_schema, arguments=arguments)
        session_id = await self._initialize(endpoint=endpoint, credential=credential)
        result, _ = await self._rpc(
            endpoint=endpoint,
            credential=credential,
            session_id=session_id,
            request_id=2,
            method="tools/call",
            params={"name": tool_name, "arguments": dict(arguments)},
        )
        return result

    async def _initialize(
        self, *, endpoint: str, credential: tuple[str, str] | None
    ) -> str | None:
        _, headers = await self._rpc(
            endpoint=endpoint,
            credential=credential,
            session_id=None,
            request_id=1,
            method="initialize",
            params={
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mnemos", "version": "0.2.0"},
            },
        )
        return headers.get("mcp-session-id")

    async def _rpc(
        self,
        *,
        endpoint: str,
        credential: tuple[str, str] | None,
        session_id: str | None,
        request_id: int,
        method: str,
        params: Mapping[str, JsonValue],
    ) -> tuple[dict[str, JsonValue], httpx.Headers]:
        pinned_url, original_host = await resolve_and_pin(
            endpoint, allowed_private_hosts=self._allowed_private_hosts
        )
        headers = {
            "Host": original_host,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **_credential_headers(credential),
        }
        if session_id is not None:
            headers["Mcp-Session-Id"] = session_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        try:
            async with self._client.stream(
                "POST",
                pinned_url,
                headers=headers,
                json=payload,
                extensions={"sni_hostname": original_host},
                follow_redirects=False,
                timeout=self._timeout_s,
            ) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    raise UpstreamError(
                        "the MCP server refused the request",
                        reason="redirect responses are not followed",
                        status_code=response.status_code,
                    )
                if response.is_error:
                    raise UpstreamError(
                        "the MCP server refused the request",
                        reason=f"HTTP {response.status_code}",
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._response_max_bytes:
                        raise UpstreamError(
                            "the MCP server returned too much data",
                            limit_bytes=self._response_max_bytes,
                        )
                response_headers = response.headers
        except httpx.HTTPError as exc:
            raise UpstreamError(
                "the MCP server is unavailable", reason=type(exc).__name__
            ) from exc

        decoded = _decode_rpc_body(bytes(body))
        error = decoded.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            raise UpstreamError(
                "the MCP tool call failed", reason=f"JSON-RPC error {code!r}"
            )
        result = decoded.get("result")
        if not isinstance(result, dict):
            raise UpstreamError(
                "the MCP server returned an invalid response", reason="result was not an object"
            )
        return cast(dict[str, JsonValue], result), response_headers


def validate_arguments(
    *, input_schema: Mapping[str, JsonValue], arguments: Mapping[str, JsonValue]
) -> None:
    """Reject arguments locally before any tool receives them."""
    try:
        validator = Draft202012Validator(dict(input_schema))
    except SchemaError as exc:
        raise ValidationError("the tool has an invalid input schema") from exc
    errors = sorted(validator.iter_errors(dict(arguments)), key=lambda error: list(error.path))
    if not errors:
        return
    first = errors[0]
    path = ".".join(str(part) for part in first.absolute_path) or "$"
    raise ValidationError(
        "tool arguments do not match the discovered schema",
        field=path,
        reason=first.message,
    )


def _credential_headers(credential: tuple[str, str] | None) -> dict[str, str]:
    if credential is None:
        return {}
    scheme, secret = credential
    if scheme == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if scheme == "api_key":
        return {"X-API-Key": secret}
    if scheme == "none":
        return {}
    raise ValidationError("unsupported MCP credential scheme", scheme=scheme)


def _decode_rpc_body(body: bytes) -> dict[str, JsonValue]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpstreamError(
            "the MCP server returned an invalid response", reason="response was not UTF-8"
        ) from exc
    stripped = text.strip()
    if stripped.startswith("data:"):
        stripped = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in stripped.splitlines()
            if line.startswith("data:")
        )
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise UpstreamError(
            "the MCP server returned an invalid response", reason="response was not JSON"
        ) from exc
    if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0":
        raise UpstreamError(
            "the MCP server returned an invalid response", reason="invalid JSON-RPC envelope"
        )
    return cast(dict[str, JsonValue], decoded)

