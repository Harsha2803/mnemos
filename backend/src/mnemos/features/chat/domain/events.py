"""What `ChatService.stream_reply` yields, translated into SSE frames by the
router. Three events, not two: token, done, error — a client that has to guess
whether a stream ended or broke will guess wrong (TRACKER §5, deliverable 4)."""

from __future__ import annotations

from dataclasses import dataclass

from mnemos.features.chat.domain.models import ChatMessageRecord


@dataclass(frozen=True, slots=True)
class AssistantToken:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantDone:
    message: ChatMessageRecord


@dataclass(frozen=True, slots=True)
class AssistantError:
    """A model failure reached after tokens had already been sent, so the
    response has already committed to a 200 and cannot become a 502. The
    message is constant and public-safe; the diagnostic reason is logged, not
    carried here (CodingStandards §4)."""

    message: str


ChatStreamEvent = AssistantToken | AssistantDone | AssistantError
