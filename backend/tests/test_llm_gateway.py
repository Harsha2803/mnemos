"""`OllamaChatModel` — the `ChatModel` port over Ollama's `/api/chat`.

Hermetic: `httpx.MockTransport` stands in for the network, so these run without
Docker and without a pulled model. `test_chat_endpoints.py` covers the port
being *consumed* correctly; this file covers the one adapter that implements it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import httpx
import pytest

from mnemos.core.errors import DependencyUnavailableError, UpstreamError
from mnemos.core.types import MessageRole
from mnemos.features.llm.adapters.ollama import OllamaChatModel
from mnemos.features.llm.domain.model import ChatDone, ChatToken, ChatTurn

BASE_URL = "http://ollama.test:11434"
MODEL = "qwen2.5:3b-instruct"

TURNS: Sequence[ChatTurn] = [
    ChatTurn(role=MessageRole.SYSTEM, content="You are terse."),
    ChatTurn(role=MessageRole.USER, content="hello"),
]


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _ndjson(*objects: dict[str, object]) -> bytes:
    return b"\n".join(json.dumps(o).encode() for o in objects)


async def test_stream_yields_tokens_then_exactly_one_done() -> None:
    chunks = [
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo"}, "done": False},
        {
            "message": {"content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 12,
            "eval_count": 3,
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["model"] == MODEL
        assert body["stream"] is True
        return httpx.Response(200, content=_ndjson(*chunks))

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        events = [event async for event in model.stream(TURNS)]

    tokens = [e for e in events if isinstance(e, ChatToken)]
    dones = [e for e in events if isinstance(e, ChatDone)]
    assert [t.text for t in tokens] == ["Hel", "lo"]
    assert len(dones) == 1
    assert dones[0] == ChatDone(finish_reason="stop", prompt_tokens=12, completion_tokens=3)


async def test_stream_raises_upstream_error_on_a_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        with pytest.raises(UpstreamError):
            async for _ in model.stream(TURNS):
                pass


async def test_stream_raises_upstream_error_when_the_connection_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        with pytest.raises(UpstreamError):
            async for _ in model.stream(TURNS):
                pass


async def test_the_upstream_error_never_carries_the_response_body_in_its_message() -> None:
    """`UpstreamError.details` may carry the diagnostic text; `.message` — the
    one thing `MnemosError.expose_details=False` still lets a caller read
    indirectly through logging — must not, or a leaking Ollama stack trace
    becomes a leaking API response the moment somebody flips that flag."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Traceback (most recent call last): secret-internal-path")

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        with pytest.raises(UpstreamError) as excinfo:
            async for _ in model.stream(TURNS):
                pass
    assert "secret-internal-path" not in excinfo.value.message


async def test_complete_returns_the_whole_answer_in_one_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "message": {"content": "hi there"},
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 2,
            },
        )

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        result = await model.complete(TURNS)

    assert result.content == "hi there"
    assert result.finish_reason == "stop"
    assert result.prompt_tokens == 5
    assert result.completion_tokens == 2


async def test_complete_raises_upstream_error_on_a_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="model is loading")

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        with pytest.raises(UpstreamError):
            await model.complete(TURNS)


async def test_health_passes_when_the_model_is_in_the_tag_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": MODEL}, {"name": "llama3:8b"}]})

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        await model.health()  # does not raise


async def test_health_fails_when_the_model_is_not_pulled() -> None:
    """The exact failure `/readyz` must report if somebody deploys without
    pulling the model — CodingStandards §7's "fail at startup" only holds if
    this distinguishes "unreachable" from "reachable but wrong model"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        with pytest.raises(DependencyUnavailableError):
            await model.health()


async def test_health_fails_when_ollama_is_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _client(httpx.MockTransport(handler)) as client:
        model = OllamaChatModel(client=client, base_url=BASE_URL, model=MODEL, timeout_s=5)
        with pytest.raises(DependencyUnavailableError):
            await model.health()


def test_model_name_is_the_configured_model() -> None:
    model = OllamaChatModel(client=httpx.AsyncClient(), base_url=BASE_URL, model=MODEL, timeout_s=5)
    assert model.model_name == MODEL
