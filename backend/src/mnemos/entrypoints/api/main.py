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
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Every model module, imported for its side effect on `Base.metadata` before
# any ORM operation runs. `platform/db.py` documents why this has to be a
# single shared import surface; the reason it has to run *here* is that a
# feature's own adapter module only registers that feature's tables; a
# `ForeignKey("context_bundle.id")` on `chat_message` cannot be resolved
# unless something has also imported `features.context.adapters.models`, and
# nothing about importing `chat`'s router implies that it will have been.
import mnemos.platform.models  # noqa: F401
from mnemos.core.clock import SYSTEM_CLOCK
from mnemos.core.config import Settings, get_settings
from mnemos.core.crypto import DsnCipher
from mnemos.core.errors import MnemosError
from mnemos.core.ids import DEFAULT_ID_GENERATOR
from mnemos.core.logging import configure_logging, get_logger, request_id_var
from mnemos.core.security import PasswordHasher
from mnemos.entrypoints.api.routers import auth as auth_router
from mnemos.entrypoints.api.routers import bookmarks as bookmarks_router
from mnemos.entrypoints.api.routers import chat as chat_router
from mnemos.entrypoints.api.routers import connectors as connectors_router
from mnemos.entrypoints.api.routers import context as context_router
from mnemos.entrypoints.api.routers import folders as folders_router
from mnemos.entrypoints.api.routers import knowledge as knowledge_router
from mnemos.entrypoints.api.routers import memory as memory_router
from mnemos.entrypoints.api.routers import tools as tools_router
from mnemos.entrypoints.api.security import (
    bind_caller_context,
    enforce_authentication,
    public_route_paths,
    reset_caller_context,
)
from mnemos.features.chat.adapters.repository import SqlChatRepository
from mnemos.features.chat.application.bookmarks import BookmarkService
from mnemos.features.chat.application.folders import FolderService
from mnemos.features.chat.application.service import ChatService
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.adapters.repository import ContentSourceRepository
from mnemos.features.connectors.application.factory import ConnectorFactory
from mnemos.features.connectors.application.service import ConnectorService
from mnemos.features.context.adapters.repository import SqlContextRepository
from mnemos.features.context.application import ContextService
from mnemos.features.datasources.adapters.executor import PostgresExecutor
from mnemos.features.datasources.adapters.introspection import PostgresIntrospector
from mnemos.features.datasources.adapters.repository import (
    DatasourceRepository,
    GlossaryRepository,
    SchemaObjectRepository,
    SqlRunRepository,
)
from mnemos.features.datasources.application.generation import SqlGenerationService
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.datasources.domain import DEFAULT_DATASOURCE_SLUG
from mnemos.features.identity.adapters.directory import SqlOrgDirectory, SqlUserDirectory
from mnemos.features.identity.adapters.login_state import RedisLoginStateStore
from mnemos.features.identity.adapters.principals import SqlPrincipalRepository
from mnemos.features.identity.adapters.sessions import SqlAppUserStore, SqlSessionStore
from mnemos.features.identity.application.oidc_login import OidcLoginFlow
from mnemos.features.identity.application.principals import AuthenticatedCaller, PrincipalResolver
from mnemos.features.identity.application.tokens import TokenService
from mnemos.features.identity.providers import (
    HttpJwksCache,
    HttpOidcMetadata,
    PlatformTokenCodec,
    PlatformTokenConfig,
    ProviderFactory,
)
from mnemos.features.knowledge.adapters.jobs_repository import IngestJobRepository
from mnemos.features.knowledge.adapters.repository import KnowledgeRepository
from mnemos.features.knowledge.adapters.retrieval import SqlRetriever
from mnemos.features.knowledge.application.service import KnowledgeService
from mnemos.features.knowledge.domain import HashingEmbedder, HeuristicTokenizer
from mnemos.features.llm.adapters.ollama import OllamaChatModel
from mnemos.features.memory.adapters.repository import SqlMemoryRepository
from mnemos.features.memory.application import MemoryService
from mnemos.features.tools.adapters.crypto import ToolCredentialCipher
from mnemos.features.tools.adapters.mcp_http import StreamableHttpMcpClient
from mnemos.features.tools.adapters.repository import SqlToolRepository
from mnemos.features.tools.application import ToolCatalogService, ToolInvocationService
from mnemos.flows.nl2sql.application import Nl2SqlFlow
from mnemos.flows.rag.application import RagFlow
from mnemos.flows.router.application import RouterService
from mnemos.flows.tools.application import ToolFlow
from mnemos.platform.cache import Cache
from mnemos.platform.db import Database
from mnemos.platform.objectstore.s3 import S3ObjectStore

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(
        json_output=not settings.is_local, session_log_enabled=settings.session_log_enabled
    )

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
    codec = PlatformTokenCodec(
        config=PlatformTokenConfig(
            secret=settings.jwt_secret.get_secret_value(),
            issuer=settings.jwt_issuer,
            algorithm=settings.jwt_algorithm,
            access_ttl_s=settings.access_token_ttl_s,
            min_secret_length=settings.jwt_min_secret_length,
        ),
        clock=SYSTEM_CLOCK,
        ids=DEFAULT_ID_GENERATOR,
    )
    app.state.token_service = TokenService(
        orgs=SqlOrgDirectory(app.state.db),
        users=SqlAppUserStore(app.state.db, DEFAULT_ID_GENERATOR),
        sessions=SqlSessionStore(app.state.db, DEFAULT_ID_GENERATOR),
        codec=codec,
        clock=SYSTEM_CLOCK,
        refresh_ttl_s=settings.refresh_token_ttl_s,
    )
    # The same codec object on both sides. One `PlatformTokenConfig` means the
    # guard cannot end up verifying against a secret, issuer or algorithm the
    # minter is not using — a divergence that would present as "everyone is
    # signed out" and would be looked for anywhere but here.
    app.state.principals = PrincipalResolver(
        codec=codec,
        repository=SqlPrincipalRepository(app.state.db),
        clock=SYSTEM_CLOCK,
    )

    # --- chat: the LLM gateway over Ollama, behind the `ChatModel` port -----
    # One `httpx.AsyncClient` for the model server, separate from `app.state.http`
    # (which follows redirects for the OIDC round trip): a chat request must
    # never silently follow a redirect to somewhere that is not Ollama.
    app.state.ollama_http = httpx.AsyncClient()
    app.state.chat_model = OllamaChatModel(
        client=app.state.ollama_http,
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_s=float(settings.ollama_timeout_s),
    )
    chat_repository = SqlChatRepository(app.state.db, DEFAULT_ID_GENERATOR)
    app.state.folder_service = FolderService(repository=chat_repository)
    app.state.bookmark_service = BookmarkService(repository=chat_repository)
    app.state.memory_service = MemoryService(
        repository=SqlMemoryRepository(app.state.db, DEFAULT_ID_GENERATOR),
        clock=SYSTEM_CLOCK,
    )
    app.state.context_service = ContextService(
        repository=SqlContextRepository(app.state.db, DEFAULT_ID_GENERATOR),
        chat=chat_repository,
        memory=app.state.memory_service,
        tokenizer=HeuristicTokenizer(),
        clock=SYSTEM_CLOCK,
        utility_decay_tau=settings.utility_decay_tau,
        history_turns=settings.chat_history_turns,
        embedder_name=settings.embedder,
        operator_deadline_ms=settings.default_operator_deadline_ms,
    )
    app.state.chat_service = ChatService(
        repository=chat_repository,
        model=app.state.chat_model,
        history_turns=settings.chat_history_turns,
        context=app.state.context_service,
        token_budget=settings.default_token_budget,
    )
    app.state.router_service = RouterService()

    # --- knowledge: object storage, extraction, chunking, embedding, retrieval
    app.state.object_store = S3ObjectStore(
        endpoint_url=settings.object_endpoint,
        access_key=settings.object_access_key,
        secret_key=settings.object_secret_key.get_secret_value(),
        bucket=settings.object_bucket,
        region=settings.object_region,
    )
    app.state.knowledge_service = KnowledgeService(
        repository=KnowledgeRepository(app.state.db, DEFAULT_ID_GENERATOR),
        retriever=SqlRetriever(app.state.db),
        objects=app.state.object_store,
        embedder=HashingEmbedder(dim=settings.embedding_dim),
        tokenizer=HeuristicTokenizer(),
        rrf_k=settings.rrf_k,
        near_duplicate_threshold=settings.near_duplicate_threshold,
    )
    app.state.rag_flow = RagFlow(
        chat_repository=chat_repository,
        knowledge=app.state.knowledge_service,
        model=app.state.chat_model,
        token_budget=settings.default_token_budget,
        retrieval_k=settings.retrieval_k,
        context=app.state.context_service,
    )

    # --- datasources + nl2sql: generation behind the AST guard, execution as
    # `mnemos_ro`, narration. Two independent `SqlRunRepository` instances
    # below (one inside `SqlGenerationService`, one handed to `Nl2SqlFlow`
    # directly) are the same pattern as `chat_repository` above: cheap
    # adapters over the same `Database`, not shared state.
    app.state.datasource_service = DatasourceService(
        datasources=DatasourceRepository(app.state.db, DEFAULT_ID_GENERATOR),
        schema_objects=SchemaObjectRepository(app.state.db, DEFAULT_ID_GENERATOR),
        introspector=PostgresIntrospector(),
        cipher=DsnCipher(settings.dsn_encryption_key.get_secret_value()),
        glossary=GlossaryRepository(app.state.db, DEFAULT_ID_GENERATOR),
        executor=PostgresExecutor(),
    )
    app.state.sql_generation_service = SqlGenerationService(
        datasources=app.state.datasource_service,
        model=app.state.chat_model,
        sql_runs=SqlRunRepository(app.state.db, DEFAULT_ID_GENERATOR),
    )
    app.state.nl2sql_flow = Nl2SqlFlow(
        chat_repository=chat_repository,
        datasources=app.state.datasource_service,
        generation=app.state.sql_generation_service,
        sql_runs=SqlRunRepository(app.state.db, DEFAULT_ID_GENERATOR),
        model=app.state.chat_model,
        datasource_slug=DEFAULT_DATASOURCE_SLUG,
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        max_rows=settings.sql_max_rows,
        repair_attempts=settings.sql_repair_attempts,
        context=app.state.context_service,
        token_budget=settings.default_token_budget,
    )

    # --- connectors: browse a registered source, enqueue an ingest ---------
    # A dedicated client, not `app.state.http` (which follows redirects for
    # the OIDC round trip) — `adapters/http.py`'s connector deliberately
    # treats a redirect as a failure rather than following it, and sharing a
    # redirect-following client here would silently defeat that.
    app.state.connector_http = httpx.AsyncClient()
    connector_cipher = SourceConfigCipher(settings.source_encryption_key.get_secret_value())
    app.state.connector_service = ConnectorService(
        repository=ContentSourceRepository(app.state.db, DEFAULT_ID_GENERATOR),
        cipher=connector_cipher,
        factory=ConnectorFactory(
            settings=settings, cipher=connector_cipher, http_client=app.state.connector_http
        ),
        local_fs_allowed_roots=settings.local_fs_allowed_roots,
    )
    app.state.ingest_jobs = IngestJobRepository(app.state.db, DEFAULT_ID_GENERATOR)

    # --- tools: one registered, authorized, durable MCP call ---------------
    # Separate no-redirect client: following an MCP redirect could bypass the
    # endpoint that was resolved, checked, and pinned by the SSRF boundary.
    app.state.tool_http = httpx.AsyncClient(follow_redirects=False)
    tool_repository = SqlToolRepository(app.state.db, DEFAULT_ID_GENERATOR)
    tool_cipher = ToolCredentialCipher(settings.tool_encryption_key.get_secret_value())
    tool_client = StreamableHttpMcpClient(
        client=app.state.tool_http,
        timeout_s=float(settings.mcp_timeout_s),
        response_max_bytes=settings.mcp_response_max_bytes,
        allowed_private_hosts=settings.mcp_allowed_private_hosts,
    )
    app.state.tool_catalog = ToolCatalogService(
        repository=tool_repository,
        client=tool_client,
        cipher=tool_cipher,
        clock=SYSTEM_CLOCK,
        ids=DEFAULT_ID_GENERATOR,
    )
    app.state.tool_invocations = ToolInvocationService(
        repository=tool_repository,
        client=tool_client,
        cipher=tool_cipher,
        clock=SYSTEM_CLOCK,
    )
    app.state.tool_flow = ToolFlow(
        chat_repository=chat_repository,
        catalog=app.state.tool_catalog,
        invocations=app.state.tool_invocations,
        context=app.state.context_service,
        token_budget=settings.default_token_budget,
    )

    log.info("api.startup", env=str(settings.env), api_prefix=settings.api_prefix)
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.ollama_http.aclose()
        await app.state.connector_http.aclose()
        await app.state.tool_http.aclose()
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
        # **The guard, installed once, for every route there will ever be.**
        # FastAPI merges application-level dependencies into every route it
        # registers — including routers included below and routes added after
        # startup — so an endpoint that decorates itself with nothing is
        # authenticated, and the only way to be public is to be named in
        # `public_route_paths`. The opposite arrangement, a decorator somebody
        # remembers to add, fails open exactly once: on the route nobody
        # reviewed. See `entrypoints/api/security.py`.
        dependencies=[Depends(enforce_authentication)],
    )

    # Read by the guard on every request. Computed here rather than imported as
    # a constant because the auth routes hang off `api_prefix`, and a list that
    # silently stopped matching a reconfigured prefix would lock everybody out
    # of the login endpoints.
    app.state.public_route_paths = public_route_paths(settings.api_prefix)

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
            # `enforce_authentication`'s own binding is already gone by now — its
            # `finally` ran inside `call_next`, before this line — so the summary
            # log below re-binds from `request.state.caller`, which the guard
            # left behind for exactly this. Without this, the one log line that
            # actually says "this request happened" would never carry the
            # session id `core/logging.py`'s per-session file is keyed on.
            caller = getattr(request.state, "caller", None)
            caller_tokens = (
                bind_caller_context(caller) if isinstance(caller, AuthenticatedCaller) else None
            )
            try:
                log.info(
                    "http.request",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=elapsed_ms,
                )
            finally:
                if caller_tokens is not None:
                    reset_caller_context(caller_tokens)
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
            ("ollama", app.state.chat_model.health),
            ("objectstore", app.state.object_store.health),
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
            "milestone": "A2 — ask about your documents: upload, extract, "
            "chunk, embed onto pgvector, retrieve, and cite; the database "
            "(A3) is next",
        }

    app.include_router(auth_router.router, prefix=settings.api_prefix)
    app.include_router(chat_router.router, prefix=settings.api_prefix)
    app.include_router(folders_router.router, prefix=settings.api_prefix)
    app.include_router(bookmarks_router.router, prefix=settings.api_prefix)
    app.include_router(knowledge_router.router, prefix=settings.api_prefix)
    app.include_router(connectors_router.router, prefix=settings.api_prefix)
    app.include_router(tools_router.router, prefix=settings.api_prefix)
    app.include_router(memory_router.router, prefix=settings.api_prefix)
    app.include_router(context_router.router, prefix=settings.api_prefix)

    return app


app = create_app()
