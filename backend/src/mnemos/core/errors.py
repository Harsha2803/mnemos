"""Domain error hierarchy.

Errors carry an HTTP status and a stable machine-readable `code`. The API layer
translates them once, in one exception handler, so no handler needs to know how
to phrase a 404. The `code` is part of the contract: clients branch on it, and
it must not change when the human-readable message is reworded.
"""

from __future__ import annotations

from typing import Any


class MnemosError(Exception):
    """Base for every error this application raises deliberately."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, /, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigurationError(MnemosError):
    """Raised at startup only. The process should not continue."""

    status_code = 500
    code = "configuration_error"


class NotFoundError(MnemosError):
    status_code = 404
    code = "not_found"


class ConflictError(MnemosError):
    status_code = 409
    code = "conflict"


class ValidationError(MnemosError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(MnemosError):
    status_code = 401
    code = "unauthenticated"


class AuthorizationError(MnemosError):
    """Deny. Never leak whether the resource exists — the message must read the
    same for "no such document" and "not yours"."""

    status_code = 403
    code = "forbidden"


class RateLimitError(MnemosError):
    status_code = 429
    code = "rate_limited"


class UpstreamError(MnemosError):
    """A dependency we do not control failed (Ollama, MinIO, an MCP server)."""

    status_code = 502
    code = "upstream_error"


class DependencyUnavailableError(MnemosError):
    """A dependency we do control is not ready. Distinct from `UpstreamError`
    because this one means *do not route traffic here yet*."""

    status_code = 503
    code = "dependency_unavailable"
