"""`ChatModel` over Ollama's `/api/chat`.

Ollama's streaming response is newline-delimited JSON, one object per line, the
last one carrying `"done": true` plus the counts. That shape is Ollama's; nothing
above `adapters/` should ever parse it — `ChatToken`/`ChatDone` in `domain/model.py`
are the only vocabulary the rest of the system is written in.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import httpx

from mnemos.core.errors import DependencyUnavailableError, UpstreamError
from mnemos.core.logging import get_logger
from mnemos.features.llm.domain.model import (
    ChatCompletion,
    ChatDone,
    ChatStreamEvent,
    ChatToken,
    ChatTurn,
)

log = get_logger(__name__)


class OllamaChatModel:
    """`ChatModel` implemented over a running Ollama server."""

    def __init__(
        self, *, client: httpx.AsyncClient, base_url: str, model: str, timeout_s: float
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s

    @property
    def model_name(self) -> str:
        return self._model

    async def stream(self, messages: Sequence[ChatTurn]) -> AsyncIterator[ChatStreamEvent]:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST", f"{self._base_url}/api/chat", json=payload, timeout=self._timeout_s
            ) as response:
                if response.status_code != httpx.codes.OK:
                    body = await response.aread()
                    raise UpstreamError(
                        "ollama chat request failed",
                        status_code=response.status_code,
                        body=body[:500].decode("utf-8", errors="replace"),
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    yield _parse_chunk(line)
        except httpx.HTTPError as exc:
            raise UpstreamError("ollama is unreachable mid-stream", reason=str(exc)) from exc

    async def complete(self, messages: Sequence[ChatTurn]) -> ChatCompletion:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": False,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat", json=payload, timeout=self._timeout_s
            )
        except httpx.HTTPError as exc:
            raise UpstreamError("ollama is unreachable", reason=str(exc)) from exc
        if response.status_code != httpx.codes.OK:
            raise UpstreamError(
                "ollama chat request failed",
                status_code=response.status_code,
                body=response.text[:500],
            )
        data = response.json()
        return ChatCompletion(
            content=data["message"]["content"],
            finish_reason=data.get("done_reason") or "stop",
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )

    async def health(self) -> None:
        """Confirm Ollama answers and the configured model is pulled.

        `/api/tags` rather than `/api/chat` with a throwaway prompt: it costs no
        inference and answers instantly, which is what a readiness probe wants.
        """
        try:
            response = await self._client.get(f"{self._base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DependencyUnavailableError("ollama is unreachable", reason=str(exc)) from exc
        names = {m.get("name") for m in response.json().get("models", [])}
        if self._model not in names:
            raise DependencyUnavailableError(
                f"model {self._model!r} is not pulled", available=sorted(n for n in names if n)
            )


def _parse_chunk(line: str) -> ChatStreamEvent:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise UpstreamError("ollama sent a line that was not JSON", line=line[:200]) from exc
    if data.get("done"):
        return ChatDone(
            finish_reason=data.get("done_reason") or "stop",
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )
    return ChatToken(text=data.get("message", {}).get("content", ""))
