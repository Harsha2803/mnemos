"""Domain error hierarchy.

Errors carry an HTTP status and a stable machine-readable `code`. The API layer
translates them once, in one exception handler, so no handler needs to know how
to phrase a 404. The `code` is part of the contract: clients branch on it, and
it must not change when the human-readable message is reworded.

**`details` is diagnostic and does not cross the API boundary by default.** An
error has two audiences (CodingStandards §4): the client gets a stable,
non-leaking response, and the log gets the truth. `details` is the second one.
Spreading it into the response body is how an internal reason escapes — and for
`AuthenticationError` specifically it is how "no such user" versus "wrong
password" becomes a user-enumeration oracle, which is precisely what the identity
providers keep out of `message`.

A subclass that opts in with `expose_details = True` is asserting that its
details are part of the public contract. `ValidationError` does, because naming
the offending field *is* the useful answer and reveals nothing the caller did not
send.
"""

from __future__ import annotations

from typing import Any, ClassVar


class MnemosError(Exception):
    """Base for every error this application raises deliberately."""

    status_code: int = 500
    code: str = "internal_error"

    #: Whether `details` may be rendered to the client. Deny by default, so a new
    #: error type leaks nothing until someone decides it should.
    expose_details: ClassVar[bool] = False

    def __init__(self, message: str, /, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    @property
    def public_details(self) -> dict[str, Any]:
        """The subset of `details` the client is allowed to see."""
        return dict(self.details) if self.expose_details else {}


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
    """The one error whose details are public: which field was wrong, and why.

    Safe because the caller sent the value being complained about, and useless
    without it — a 422 that will not say what failed is a 422 nobody can act on.
    """

    status_code = 422
    code = "validation_error"
    expose_details = True


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


class SsrfRejectedError(ValidationError):
    """A connector URL resolved to (or was itself) a denied address range.

    Subclasses `ValidationError` rather than adding a new status code: from
    the caller's point of view this is the same kind of thing — an
    operator-supplied value that fails a check — and `expose_details = True`
    is exactly right here too, since the offending host/address is not a
    secret and naming it is the useful answer (ThreatModel.md §3⑥).
    """

    code = "ssrf_rejected"


class UpstreamError(MnemosError):
    """A dependency we do not control failed (Ollama, MinIO, an MCP server)."""

    status_code = 502
    code = "upstream_error"


class DependencyUnavailableError(MnemosError):
    """A dependency we do control is not ready. Distinct from `UpstreamError`
    because this one means *do not route traffic here yet*."""

    status_code = 503
    code = "dependency_unavailable"
