"""FastAPI application.

Liveness and readiness are deliberately different endpoints. `/healthz` answers
"is this process alive" and touches nothing, so a database blip cannot cause the
orchestrator to kill an otherwise healthy container. `/readyz` answers "should
traffic be routed here" and does check dependencies. Collapsing the two turns a
transient Postgres restart into a rolling container kill.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mnemos.core.clock import SYSTEM_CLOCK
from mnemos.core.config import Settings, get_settings
from mnemos.core.errors import MnemosError
from mnemos.core.ids import DEFAULT_ID_GENERATOR
from mnemos.core.logging import configure_logging, get_logger, request_id_var
from mnemos.core.security import PasswordHasher
from mnemos.entrypoints.api.routers import auth as auth_router
from mnemos.features.identity.adapters.directory import SqlOrgDirectory, SqlUserDirectory
from mnemos.features.identity.adapters.login_state import RedisLoginStateStore
from mnemos.features.identity.adapters.sessions import SqlAppUserStore, SqlSessionStore
from mnemos.features.identity.application.oidc_login import OidcLoginFlow
from mnemos.features.identity.application.tokens import TokenService
from mnemos.features.identity.providers import (
    HttpJwksCache,
    HttpOidcMetadata,
    PlatformTokenCodec,
    PlatformTokenConfig,
    ProviderFactory,
)
from mnemos.platform.cache import Cache
from mnemos.platform.db import Database

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(json_output=not settings.is_local)

    app.state.settings = settings
    app.state.db = Database(settings)
    app.state.cache = Cache(settings)

    # --- identity composition root -------------------------------------
    # Built once per process, not per request. The hasher holds the argon2
    # parameters; the JWKS and discovery caches only earn their keep by
    # outliving a request, and rebuilding them per call would turn the IdP into
    # a dependency of every authenticated hop.
    app.state.http = httpx.AsyncClient(follow_redirects=False)
    metadata = HttpOidcMetadata(client=app.state.http, ttl_s=settings.oidc_jwks_cache_s)
    app.state.provider_factory = ProviderFactory(
        orgs=SqlOrgDirectory(app.state.db),
        users=SqlUserDirectory(app.state.db),
        hasher=PasswordHasher(),
        jwks=HttpJwksCache(
            client=app.state.http,
            ttl_s=settings.oidc_jwks_cache_s,
            metadata=metadata,
        ),
    )
    app.state.oidc_login = OidcLoginFlow(
        factory=app.state.provider_factory,
        metadata=metadata,
        states=RedisLoginStateStore(app.state.cache.client),
        client=app.state.http,
        state_ttl_s=settings.oidc_login_state_ttl_s,
    )
    # `PlatformTokenConfig` validates the secret, the algorithm and the TTL here,
    # in the lifespan — so a deployment with an unusable signing secret fails to
    # start rather than failing at somebody's first login (CodingStandards §7).
    app.state.token_service = TokenService(
        orgs=SqlOrgDirectory(app.state.db),
        users=SqlAppUserStore(app.state.db, DEFAULT_ID_GENERATOR),
        sessions=SqlSessionStore(app.state.db, DEFAULT_ID_GENERATOR),
        codec=PlatformTokenCodec(
            config=PlatformTokenConfig(
                secret=settings.jwt_secret.get_secret_value(),
                issuer=settings.jwt_issuer,
                algorithm=settings.jwt_algorithm,
                access_ttl_s=settings.access_token_ttl_s,
                min_secret_length=settings.jwt_min_secret_length,
            ),
            clock=SYSTEM_CLOCK,
            ids=DEFAULT_ID_GENERATOR,
        ),
        clock=SYSTEM_CLOCK,
        refresh_ttl_s=settings.refresh_token_ttl_s,
    )

    log.info("api.startup", env=str(settings.env), api_prefix=settings.api_prefix)
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.cache.close()
        await app.state.db.dispose()
        log.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        summary="Chat over documents, databases and tools, with governed memory "
        "and compiled context.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # `allow_credentials=True` is what lets the frontend at :3000 send and receive
    # the `httpOnly` refresh cookie cross-origin. It only works alongside an
    # explicit origin list: a browser refuses a credentialed response whose
    # `Access-Control-Allow-Origin` is `*`, so `cors_origins` must stay a list of
    # real origins and must never be widened to a wildcard "to make CORS work".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        # Honour an inbound id so a trace survives the hop from the gateway.
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-Id"] = request_id
        if request.url.path not in {"/healthz", "/readyz"}:
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=elapsed_ms,
            )
        return response

    @app.exception_handler(MnemosError)
    async def handle_domain_error(request: Request, exc: MnemosError) -> JSONResponse:
        # One translation point. No handler needs to know how to phrase a 404.
        #
        # The full `details` goes to the log; only `public_details` goes to the
        # client. Spreading `details` into the body — which this handler used to
        # do — defeats every error message the identity layer is careful about:
        # `AuthenticationError` deliberately carries a constant `message` and puts
        # the real reason in `details`, so rendering both hands the caller the
        # "no such user" / "wrong password" distinction it was built to withhold.
        log.warning(
            "http.domain_error",
            code=exc.code,
            status=exc.status_code,
            path=request.url.path,
            message=exc.message,
            **exc.details,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, **exc.public_details}},
        )

    @app.get("/healthz", tags=["system"], summary="Liveness — touches no dependency")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"], summary="Readiness — checks dependencies")
    async def readyz() -> JSONResponse:
        checks: dict[str, str] = {}
        for name, probe in (
            ("postgres", app.state.db.ping),
            ("redis", app.state.cache.ping),
        ):
            try:
                await probe()
                checks[name] = "ok"
            except Exception as exc:
                checks[name] = f"error: {type(exc).__name__}"

        ready = all(v == "ok" for v in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": "0.2.0",
            "docs": "/docs",
            "milestone": "M3 — identity: OIDC login issues a platform JWT with "
            "refresh rotation; API keys and RBAC next",
        }

    app.include_router(auth_router.router, prefix=settings.api_prefix)

    return app


app = create_app()
