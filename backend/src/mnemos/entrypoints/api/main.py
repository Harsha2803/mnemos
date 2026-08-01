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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mnemos.core.config import Settings, get_settings
from mnemos.core.errors import MnemosError
from mnemos.core.logging import configure_logging, get_logger, request_id_var
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

    log.info("api.startup", env=str(settings.env), api_prefix=settings.api_prefix)
    try:
        yield
    finally:
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
            "milestone": "M2 — schema applied; feature routers land from M3",
        }

    return app


app = create_app()
