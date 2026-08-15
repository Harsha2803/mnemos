"""What `ChatService.stream_reply` yields, translated into SSE frames by the
router. Three events, not two: token, done, error — a client that has to guess
whether a stream ended or broke will guess wrong (TRACKER §5, deliverable 4)."""

from __future__ import annotations

from dataclasses import dataclass

from mnemos.core.types import JsonValue
from mnemos.features.chat.domain.models import ChatMessageRecord


@dataclass(frozen=True, slots=True)
class AssistantToken:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantDone:
    message: ChatMessageRecord
    #: Flow-specific payload merged into the `done` SSE frame verbatim.
    #: `RagFlow` leaves this `None` — citations are read back from the session
    #: refetch, not carried here. `flows/nl2sql` is the first flow that needs
    #: it: the SQL, verdict, rows and truncation flag are only ever produced
    #: once, in the same request that produces `message`, so shipping them in
    #: the terminal SSE frame is the one place they cannot be lost to a
    #: refetch race. `features/chat` stays ignorant of the shape inside —
    #: only `dict[str, JsonValue]` is guaranteed, never a `datasources` type.
    extra: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class AssistantError:
    """A model failure reached after tokens had already been sent, so the
    response has already committed to a 200 and cannot become a 502. The
    message is constant and public-safe; the diagnostic reason is logged, not
    carried here (CodingStandards §4)."""

    message: str


ChatStreamEvent = AssistantToken | AssistantDone | AssistantError
