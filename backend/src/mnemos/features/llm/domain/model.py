"""The chat model port.

``ChatModel`` is deliberately narrow: stream, complete, health. Everything above
this line — chat persistence, SSE framing, the router's flow choice, the cost
ledger — depends on the *port*, never on Ollama. That is not decoration: C1 (zero
paid dependencies in the default path) means Ollama is the default forever, and
``A4``'s router and ``C2``'s cost ledger both need to swap the model without
touching a call site. A fake implementing this port is also what keeps the chat
tests hermetic rather than dependent on a running model server.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from mnemos.core.types import MessageRole


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """One turn of the conversation as the model sees it — role and text only.

    Deliberately not `ChatMessageRecord` (`features/chat/domain`): the model
    should never be handed persistence metadata (ids, ordinals, token counts),
    and a port that accepted the richer type would make every future model
    adapter — including a test fake — depend on the chat schema.
    """

    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ChatToken:
    """One piece of the streamed completion."""

    text: str


@dataclass(frozen=True, slots=True)
class ChatDone:
    """Terminal event of a stream: how it ended and what it cost."""

    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


ChatStreamEvent = ChatToken | ChatDone


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    """The non-streaming shape — one call, one answer."""

    content: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


class ChatModel(Protocol):
    """A model that can stream a completion, produce one in a single call, and
    report whether it is reachable."""

    @property
    def model_name(self) -> str:
        """Recorded on every persisted message (`chat_message.model`) — the
        column that makes "which model answered this" a stored fact rather
        than an inference from when the row was written."""
        ...

    def stream(self, messages: Sequence[ChatTurn]) -> AsyncIterator[ChatStreamEvent]:
        """Tokens as they are generated, terminated by exactly one `ChatDone`.

        An `AsyncIterator` rather than an `AsyncGenerator` in the signature: the
        port promises consumption, not the generator machinery a particular
        implementation happens to use.
        """
        ...

    async def complete(self, messages: Sequence[ChatTurn]) -> ChatCompletion:
        """The whole answer in one call. Not used by the streaming endpoint —
        kept because a non-streaming caller (`A4`'s router, classifying a
        message) needs the port without needing to drain a stream for one
        short answer."""
        ...

    async def health(self) -> None:
        """Raise if the model is not reachable or not pulled.

        Called from `/readyz` (CodingStandards §7: fail at startup, not at
        somebody's first message) rather than only on the first chat request.
        """
        ...
