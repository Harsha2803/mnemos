"""Authentication routes: the OIDC authorization-code round trip.

Thin on purpose. The flow lives in
``features/identity/application/oidc_login.py``; this module translates HTTP into
a call and a result back into HTTP, and holds no authentication logic of its own.
That is what keeps the flow testable without a web framework and keeps
``providers/`` free of FastAPI.

**The org is a query parameter here and only here.** `APIContract.md` §1 says
tenancy is derived from the credential and never from a header or query
parameter — and that rule governs *authenticated* requests, which this is not.
The whole point of `authorize` is that the caller has no credential yet, and RLS
means nothing about them is readable until an org is known. After this step the
org travels inside signed state, and from M3.4 inside the token.

**No platform token is issued here.** M3.3 ends at a verified subject; minting a
JWT and opening a session row is M3.4. The callback's response shape changes
then, and says so below.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from mnemos.features.identity.application.oidc_login import OidcLoginFlow
from mnemos.features.identity.providers import denied

router = APIRouter(prefix="/auth", tags=["auth"])


class SubjectResponse(BaseModel):
    """The verified subject.

    **Interim.** M3.4 replaces this with an access/refresh token pair; it is here
    so the flow is end-to-end testable now rather than half-built behind a
    feature flag. It deliberately carries no roles or tags — those are resolved
    per request against the live database so a revoked role takes effect at once.
    """

    org_slug: str
    provider: str = Field(description="Slug of the identity_provider row that authenticated this")
    external_subject: str | None = None
    email: str | None = None
    display_name: str | None = None


def _flow(request: Request) -> OidcLoginFlow:
    """The flow is built once, in the app's lifespan, and shared.

    Not a `Depends` factory: rebuilding it per request would rebuild the JWKS and
    discovery caches per request, which is precisely what they exist to avoid.
    """
    flow = getattr(request.app.state, "oidc_login", None)
    if flow is None:  # pragma: no cover - only reachable if the lifespan changed
        msg = "OIDC login flow is not configured"
        raise RuntimeError(msg)
    return flow


@router.get(
    "/oidc/authorize",
    summary="Begin OIDC authorization code + PKCE",
    response_class=RedirectResponse,
    status_code=307,
)
async def oidc_authorize(
    request: Request,
    org: Annotated[str, Query(min_length=1, max_length=128, description="Org slug to log into")],
    provider: Annotated[
        str | None, Query(description="Provider slug; the org default if omitted")
    ] = None,
) -> RedirectResponse:
    """302 the browser to the IdP's **public** issuer.

    307 rather than 302 in the OpenAPI declaration only; `RedirectResponse`
    defaults to 307 and the method is GET either way, so no body is at stake.
    """
    settings = request.app.state.settings
    redirect = await _flow(request).begin(
        org_slug=org,
        provider_slug=provider,
        redirect_uri=settings.oidc_redirect_uri,
    )
    return RedirectResponse(redirect.url)


@router.get("/oidc/callback", summary="OIDC callback: exchange the code for a subject")
async def oidc_callback(
    request: Request,
    state: Annotated[str, Query(min_length=1, max_length=512)],
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> SubjectResponse:
    """Verify `state`, exchange `code` server-side, validate the returned token.

    `error` is what the IdP sends when the user cancels or is refused. It is a
    denial like any other and must not be echoed back — the IdP's error strings
    are diagnostic and can name internal configuration.
    """
    if error is not None or code is None:
        raise denied(f"IdP returned error={error!r}, code_present={code is not None}")

    completed = await _flow(request).complete(state=state, code=code)
    return SubjectResponse(
        # Both of these come from the state stored before the redirect, never
        # from this request's query string.
        org_slug=completed.org_slug,
        provider=completed.provider_slug or str(completed.subject.provider_kind),
        external_subject=completed.subject.external_subject,
        email=completed.subject.email,
        display_name=completed.subject.display_name,
    )
