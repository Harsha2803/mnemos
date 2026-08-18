"""A tiny streamable-HTTP MCP server used by B3's reproducible demo."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from mnemos.core.types import JsonValue

app = FastAPI(title="Mnemos demo MCP", version="1.0.0")


class RpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"]
    id: int
    method: str
    # Pydantic 2.13 recursively expands the recursive ``JsonValue`` alias when
    # it is used on a model field and can exhaust Python's recursion limit at
    # import time. The MCP handler narrows every value it consumes below.
    params: dict[str, object] = Field(default_factory=dict)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(request: RpcRequest) -> JSONResponse:
    if request.method == "initialize":
        return _result(
            request.id,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mnemos-demo", "version": "1.0.0"},
            },
            session_id="mnemos-demo-session",
        )
    if request.method == "tools/list":
        return _result(
            request.id,
            {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Return a deterministic message for the Mnemos demo.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"message": {"type": "string", "maxLength": 500}},
                            "required": ["message"],
                            "additionalProperties": False,
                        },
                        "annotations": {"readOnlyHint": True},
                    }
                ]
            },
        )
    if request.method == "tools/call":
        name = request.params.get("name")
        arguments = request.params.get("arguments")
        if name != "echo" or not isinstance(arguments, dict):
            return _error(request.id, -32602, "unknown tool or invalid arguments")
        message = arguments.get("message")
        if not isinstance(message, str):
            return _error(request.id, -32602, "message must be a string")
        return _result(
            request.id,
            {
                "content": [{"type": "text", "text": f"Mnemos demo echo: {message}"}],
                "structuredContent": {"echo": message},
                "isError": False,
            },
        )
    return _error(request.id, -32601, "method not found")


def _result(
    request_id: int, result: dict[str, JsonValue], *, session_id: str | None = None
) -> JSONResponse:
    headers = {"Mcp-Session-Id": session_id} if session_id is not None else None
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result}, headers=headers)


def _error(request_id: int, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )
