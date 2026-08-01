"""The API error boundary: what a raised `MnemosError` tells the client.

Errors have two audiences (CodingStandards §4). The client gets a stable,
non-leaking body; the log gets the diagnostic truth. The single exception handler
in `entrypoints/api/main.py` is the one place that split is enforced, so it is the
one place worth a test — every feature from M3 on inherits whatever it does.

This exists because the handler originally spread `exc.details` into the response.
That is invisible until something puts a secret in `details`, and M3.2 did exactly
that: `AuthenticationError` carries a constant `message` and the real reason —
"no such user" versus "password mismatch" — in `details`. Rendering both would
have handed callers the user-enumeration distinction the provider layer is built
to withhold, while every provider-level test still passed, because they assert on
the exception and never on the wire.

Hermetic: `Database` and `Cache` construct lazily, so the app's lifespan runs
without Postgres or Redis. Nothing here touches `/readyz`, which is the only route
that dials out.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mnemos.core.errors import (
    AuthenticationError,
    AuthorizationError,
    MnemosError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
from mnemos.entrypoints.api.main import create_app
from mnemos.features.identity.providers import AUTHENTICATION_FAILED, denied


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The real application, with probe routes that raise what handlers raise."""
    app = create_app()

    async def raise_denial() -> None:
        raise denied("no such user")

    async def raise_upstream() -> None:
        raise UpstreamError(
            "ollama call failed",
            dsn="postgresql://mnemos:hunter2@postgres:5432/mnemos",
            sql="SELECT * FROM app_user WHERE email = 'ada@example.test'",
        )

    async def raise_validation() -> None:
        raise ValidationError("token budget must be positive", field="budget", got=-1)

    for path, endpoint in (
        ("/_probe/denial", raise_denial),
        ("/_probe/upstream", raise_upstream),
        ("/_probe/validation", raise_validation),
    ):
        app.add_api_route(path, endpoint, methods=["GET"])

    with TestClient(app) as test_client:
        return test_client


def test_an_authentication_denial_leaks_no_reason(client: TestClient) -> None:
    """The regression this file was written for."""
    response = client.get("/_probe/denial")

    assert response.status_code == 401
    body = response.json()
    assert body == {"error": {"code": "unauthenticated", "message": AUTHENTICATION_FAILED}}
    # Belt and braces: the reason must not appear anywhere in the payload, under
    # any key, however the body is later restructured.
    assert "no such user" not in response.text
    assert "reason" not in response.text


def test_internal_diagnostics_never_cross_the_boundary(client: TestClient) -> None:
    """A DSN with a password in it, and a SQL fragment. Neither is the client's."""
    response = client.get("/_probe/upstream")

    assert response.status_code == 502
    assert response.json() == {"error": {"code": "upstream_error", "message": "ollama call failed"}}
    for secret in ("hunter2", "postgresql://", "SELECT", "app_user"):
        assert secret not in response.text


def test_validation_details_are_public_because_the_caller_sent_them(
    client: TestClient,
) -> None:
    """The one opt-in. A 422 that will not say which field failed is unactionable."""
    response = client.get("/_probe/validation")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "token budget must be positive",
            "field": "budget",
            "got": -1,
        }
    }


def test_details_are_withheld_by_default_for_every_error_type() -> None:
    """Deny by default: a new error class leaks nothing until someone opts in.

    Asserted over the hierarchy rather than one instance, so adding a subclass
    that quietly sets `expose_details = True` has to be a deliberate edit that
    fails here first.
    """
    assert MnemosError("m", secret="s").public_details == {}
    for cls in (AuthenticationError, AuthorizationError, NotFoundError, UpstreamError):
        assert cls.expose_details is False
        assert cls("m", secret="s").public_details == {}
    # And the details are still there for the log — withheld, not discarded.
    assert AuthenticationError("m", secret="s").details == {"secret": "s"}
    assert ValidationError.expose_details is True


def test_the_denial_helper_matches_what_the_boundary_renders() -> None:
    """`denied()` is only safe because of the handler above it; pin them together
    so neither can be changed without the other failing."""
    error = denied("password mismatch")
    assert error.message == AUTHENTICATION_FAILED
    assert error.public_details == {}
    assert error.details == {"reason": "password mismatch"}
