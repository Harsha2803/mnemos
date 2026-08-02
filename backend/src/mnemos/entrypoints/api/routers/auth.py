"""Authentication routes: the OIDC round trip, and the token pair it produces.

Thin on purpose. The flow lives in
``features/identity/application/oidc_login.py`` and the token machinery in
``features/identity/application/tokens.py``; this module translates HTTP into a
call and a result back into HTTP, and holds no authentication logic of its own.
That is what keeps both testable without a web framework and keeps
``providers/`` free of FastAPI.

**The org is a query parameter here and only here.** `APIContract.md` §1 says
tenancy is derived from the credential and never from a header or query
parameter — and that rule governs *authenticated* requests, which `authorize` is
not. The whole point of it is that the caller has no credential yet, and RLS
means nothing about them is readable until an org is known. After this step the
org travels inside signed state, and then inside the credential itself.

**The refresh token leaves in a cookie and never in a body.** `httpOnly`, so no
script can read it — `localStorage` is readable by any XSS, and the refresh token
is the credential worth stealing. `SameSite=Lax` plus POST-only endpoints is what
makes it safe to *accept* back: Lax withholds the cookie from cross-site POSTs,
so a form on another origin submitting to `/auth/token` sends nothing and the
request is merely an unauthenticated one. `Path` is scoped to the auth routes, so
the browser does not attach it to every other API call.

A non-browser client may send the token in the request body instead; both
endpoints read the body first and fall back to the cookie. Deliberately *not* a
`refresh_token` field in the response — see :class:`TokenResponse`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from mnemos.core.config import Settings
from mnemos.features.identity.application.oidc_login import OidcLoginFlow
from mnemos.features.identity.application.tokens import TokenService
from mnemos.features.identity.domain import TokenPair
from mnemos.features.identity.providers import denied

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    """A minted access token, and where to send it.

    **There is no `refresh_token` field, and that is the design.** The refresh
    token is set as an `httpOnly` cookie on this same response; returning it in
    the body would invite a browser client to keep it in `localStorage`, which
    any cross-site scripting bug can read. A response body is also the thing most
    likely to end up in a log, a proxy cache, or a pasted bug report.

    `APIContract.md` §2 used to show a `refresh_token` field. It is corrected in
    the same commit as this class rather than left to disagree with the code.

    No `scope` field either: an access token carries identity and no
    authorization, so there is no scope to report. Effective permissions come
    from `GET /auth/me` (M3.6) against the live database, which is what makes a
    revoked role take effect on the next request rather than in fifteen minutes.
    """

    access_token: str = Field(description="Bearer token, 15 minutes, identity claims only")
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    org_slug: str = Field(description="Tenant this session belongs to")


class TokenRequest(BaseModel):
    """`grant_type=refresh_token`.

    `refresh_token` is optional because a browser sends it as an `httpOnly`
    cookie and has no way to read it back into a body. A non-browser client that
    holds its own token sends it here instead.
    """

    grant_type: Literal["refresh_token"] = Field(
        description="Only `refresh_token` is supported here. The password and "
        "api_key grants are M3.5; OIDC logins go through `/auth/oidc/authorize`."
    )
    refresh_token: str | None = Field(
        default=None,
        description="Omit when the refresh cookie is present, which is the browser case.",
    )


class RevokeRequest(BaseModel):
    refresh_token: str | None = Field(
        default=None, description="Omit when the refresh cookie is present."
    )


def _flow(request: Request) -> OidcLoginFlow:
    """The flow is built once, in the app's lifespan, and shared.

    Not a `Depends` factory: rebuilding it per request would rebuild the JWKS and
    discovery caches per request, which is precisely what they exist to avoid.
    """
    flow = getattr(request.app.state, "oidc_login", None)
    if not isinstance(flow, OidcLoginFlow):  # pragma: no cover - the lifespan sets it
        msg = "OIDC login flow is not configured"
        raise RuntimeError(msg)
    return flow


def _tokens(request: Request) -> TokenService:
    service = getattr(request.app.state, "token_service", None)
    if not isinstance(service, TokenService):  # pragma: no cover - the lifespan sets it
        msg = "token service is not configured"
        raise RuntimeError(msg)
    return service


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):  # pragma: no cover - the lifespan sets it
        msg = "settings are not configured"
        raise RuntimeError(msg)
    return settings


def _client(request: Request) -> tuple[str | None, str | None]:
    """User agent and peer address, for the audit columns on `session`.

    Recorded, never *trusted*: both are attacker-controlled, so they are evidence
    for a human reading the table after an incident and take no part in any
    authentication decision.
    """
    return request.headers.get("user-agent"), (request.client.host if request.client else None)


def _set_refresh_cookie(response: Response, settings: Settings, pair: TokenPair) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=pair.refresh_token,
        max_age=settings.refresh_token_ttl_s,
        httponly=True,
        samesite="lax",
        secure=settings.refresh_cookie_is_secure,
        path=settings.refresh_cookie_path,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    # Same name, path, `Secure` and `SameSite` as when it was set — a browser
    # matches a deletion on those, and one that differs in any of them leaves the
    # original cookie in place while appearing to have worked.
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.refresh_cookie_is_secure,
        path=settings.refresh_cookie_path,
    )


def _to_response(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        expires_in=pair.expires_in_s,
        org_slug=pair.org_slug,
    )


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
    redirect = await _flow(request).begin(
        org_slug=org,
        provider_slug=provider,
        redirect_uri=_settings(request).oidc_redirect_uri,
    )
    return RedirectResponse(redirect.url)


@router.get("/oidc/callback", summary="OIDC callback: exchange the code for a token pair")
async def oidc_callback(
    request: Request,
    response: Response,
    state: Annotated[str, Query(min_length=1, max_length=512)],
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> TokenResponse:
    """Verify `state`, exchange `code` server-side, validate the token, open a session.

    M3.3 ended here with a `SubjectResponse` — proof that a login *happened*, with
    no way to stay logged in. It now returns the access token and sets the refresh
    cookie, which is what makes a session survive a reload.

    `error` is what the IdP sends when the user cancels or is refused. It is a
    denial like any other and must not be echoed back: the IdP's error strings are
    diagnostic and can name internal configuration.
    """
    if error is not None or code is None:
        raise denied(f"IdP returned error={error!r}, code_present={code is not None}")

    completed = await _flow(request).complete(state=state, code=code)
    user_agent, ip_address = _client(request)
    pair = await _tokens(request).issue_for_subject(
        subject=completed.subject,
        # From the state stored before the redirect, never from this request's
        # query string.
        org_slug=completed.org_slug,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    _set_refresh_cookie(response, _settings(request), pair)
    return _to_response(pair)


@router.post("/token", summary="Exchange a refresh token for a new access token")
async def issue_token(request: Request, response: Response, body: TokenRequest) -> TokenResponse:
    """Rotate the refresh token and mint a fresh access token.

    **Every call rotates.** The token that came in is retired and a new one goes
    out on the cookie; presenting the retired one again revokes the entire chain,
    because at that point two parties hold copies of one credential and nothing
    here can tell which one is the thief.

    The practical consequence for a client is that *concurrent* refreshes are
    indistinguishable from theft and must be collapsed into one in-flight call.
    That is the frontend half of M3.4 and it is written down in TRACKER §5.
    """
    settings = _settings(request)
    presented = body.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    if not presented:
        raise denied("no refresh token in the request body or the cookie")

    user_agent, ip_address = _client(request)
    pair = await _tokens(request).refresh(presented, user_agent=user_agent, ip_address=ip_address)
    _set_refresh_cookie(response, settings, pair)
    return _to_response(pair)


@router.post(
    "/token:revoke",
    summary="Revoke a refresh token and its whole rotation chain",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_token(request: Request, response: Response, body: RevokeRequest) -> None:
    """Sign out. **Always 204**, whatever was presented.

    RFC 7009 §2.2 asks for the same, and the reason is worth stating: an endpoint
    that answers 401 for an unknown token and 204 for a known one is a free oracle
    for testing stolen credentials — and the caller is unauthenticated, because
    presenting the token *is* the authentication. So unknown, expired, malformed
    and absent all get one answer, and the cookie is cleared either way rather
    than leaving a client holding a credential it believes it revoked.
    """
    settings = _settings(request)
    presented = body.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    if presented:
        await _tokens(request).revoke(presented)
    _clear_refresh_cookie(response, settings)
