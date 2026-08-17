"""Application seam for message classification.

Today the service delegates to the deterministic local policy. Keeping this
seam separate lets a future Ollama classifier be added without changing the
chat route, while the domain policy remains its mandatory zero-cost fallback.
"""

from __future__ import annotations

from mnemos.flows.router.domain import RouteDecision, classify_message


class RouterService:
    """Classify a message into one of the answer flows A4 exposes."""

    def classify(self, content: str) -> RouteDecision:
        """Return a deterministic route and display-safe rationale."""

        return classify_message(content)
