"""Application settings.

Validated once at startup and failed fast. A service that boots with malformed
configuration and discovers it on the first request is a service that fails in
production rather than in CI.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Final, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


#: The signing secret a developer gets for free. Named rather than inlined so
#: that `_reject_the_dev_secret_in_production` can recognise it: a deployment
#: that forgot to set `MNEMOS_JWT_SECRET` would otherwise mint tokens anyone who
#: has read this repository can forge, and it would do so silently.
DEV_JWT_SECRET: Final = "dev-only-change-me-not-for-production-use"

#: A valid Fernet key (32 url-safe base64 bytes) so the development default
#: works out of the box, generated once and pinned here rather than derived —
#: `_reject_the_dev_secret_in_production` needs a literal to compare against.
DEV_DSN_ENCRYPTION_KEY: Final = "zqQeIteGh6YP2kybnsto8GE8W38N_u9yJhINMNKDpMg="

#: Same reasoning as `DEV_DSN_ENCRYPTION_KEY`, for `content_source.config_encrypted`
#: — a distinct key so rotating one secret does not force rotating the other.
DEV_SOURCE_ENCRYPTION_KEY: Final = "zyE7WKGQXXwuWC7pvMVZ3qbkXUliL3BRmD8Lzk89qu4="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MNEMOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = Environment.LOCAL
    app_name: str = "Mnemos"
    api_prefix: str = "/api/v1"

    # -- data -------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://mnemos_app:mnemos-app-dev@localhost:5432/mnemos"
    database_pool_size: int = 10
    database_max_overflow: int = 5
    redis_url: str = "redis://localhost:6379/0"

    # The application connects as an unprivileged role so that row-level security
    # applies to it. The role the *migrations* connect as owns the tables and is a
    # superuser, and RLS never applies to a superuser — pointing the API at that
    # role makes every policy in migration 0004 inert. Migration 0005 creates this
    # role and needs the same credentials the API will later connect with, which is
    # why they are settings rather than literals in either place.
    app_database_role: str = "mnemos_app"
    app_database_password: SecretStr = SecretStr("mnemos-app-dev")
    # NOLOGIN, BYPASSRLS. `mnemosctl bootstrap` assumes it for the one transaction
    # that has no org to scope to yet.
    admin_database_role: str = "mnemos_admin"

    # -- object storage (S3-compatible: MinIO locally, S3 in a real deployment) --
    object_endpoint: str = "http://localhost:9000"
    object_access_key: str = "mnemos"
    object_secret_key: SecretStr = SecretStr("mnemos-dev-secret")
    object_bucket: str = "mnemos-documents"
    object_region: str = "us-east-1"

    # -- inference --------------------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b-instruct"
    ollama_timeout_s: int = 180
    embedder: str = "hashing"
    embedding_dim: int = 384

    # -- auth -------------------------------------------------------------
    # HS256, and `docs/ThreatModel.md` §5.1 is where that is argued rather than
    # asserted: api/worker/realtime are one trust domain reading one secret, so
    # there is no verifier that must be unable to sign — which is the only thing
    # an asymmetric algorithm buys. The half that actually stops forgeries is the
    # fixed `algorithms=` allow-list in `providers/platform.py`, never the token's
    # own `alg` header, and that is identical under either choice.
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    # RFC 7518 §3.2: an HMAC key must be at least as long as the hash output, so
    # 32 bytes for SHA-256. Enforced rather than documented, because a short
    # secret degrades silently.
    jwt_min_secret_length: int = 32
    # `iss` on every token we mint, and the value the verifier requires. A
    # constant we control, so a token from another deployment sharing a leaked
    # secret still fails.
    jwt_issuer: str = "mnemos"
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 60 * 60 * 24 * 14

    # The refresh token reaches the browser as an httpOnly cookie and never in a
    # response body, so no script can read it — `localStorage` is readable by any
    # XSS, and a refresh token is the credential worth stealing. `SameSite=Lax` is
    # what makes the cookie safe to *accept* on the token endpoints: Lax withholds
    # the cookie from cross-site POSTs, and both endpoints are POST-only, so a
    # forged form on another origin sends nothing.
    refresh_cookie_name: str = "mnemos_refresh"
    # `None` means "derive it": never `Secure` over local http, always otherwise.
    # Hard-coding False would ship a cookie that travels in clear text; hard-coding
    # True would silently drop it in development, which looks like a broken login.
    refresh_cookie_secure: bool | None = None

    # Split-horizon OIDC. The browser is redirected to the public issuer; the API
    # fetches JWKS over the internal one. Collapsing these into a single URL is
    # the standard containerised-OIDC failure: the token's `iss` never matches
    # what the API expects.
    oidc_enabled: bool = True
    oidc_issuer_public: str = "http://localhost:8080/realms/mnemos"
    oidc_issuer_internal: str = "http://localhost:8080/realms/mnemos"
    oidc_client_id: str = "mnemos-web"
    oidc_jwks_cache_s: int = 900

    # Where Keycloak sends the browser back with the authorization code. Must be
    # registered in the realm's `redirectUris` *and* match byte-for-byte at both
    # the authorize and the token-exchange step, which is why it is one setting
    # rather than something reconstructed from the incoming request — a callback
    # that derives its own redirect URI from a `Host` header is a callback an
    # attacker can point elsewhere.
    oidc_redirect_uri: str = "http://localhost:8000/api/v1/auth/oidc/callback"
    # How long a half-finished login may sit in Redis: enough for a password and
    # MFA, short enough that an abandoned attempt is not a standing credential.
    oidc_login_state_ttl_s: int = 600

    # Where the browser is sent when a login ends, successfully or not. A
    # setting rather than anything derived from the request: a redirect target
    # taken from a `Host` header, a `Referer` or a query parameter is an open
    # redirect, and an open redirect on the *login* route is the one that
    # matters most — it is where a credential has just been minted.
    web_base_url: str = "http://localhost:3000"

    # -- context compiler defaults ---------------------------------------
    default_token_budget: int = 3000
    default_operator_deadline_ms: int = 2000
    rrf_k: int = 60
    near_duplicate_threshold: float = Field(default=0.86, ge=0.0, le=1.0)
    utility_decay_tau: float = Field(default=6.0, gt=0.0)
    # How many candidates each retrieval operator (vector, lexical) returns
    # before fusion — generous enough that RRF has something to fuse over,
    # small enough that a demo-scale corpus scan stays fast.
    retrieval_k: int = 8

    # -- nl2sql -----------------------------------------------------------
    # Separate database, read-only role. The AST guard is the second line of
    # defence, not the only one.
    analytics_database_url: str = (
        "postgresql+asyncpg://mnemos_ro:mnemos_ro_dev@localhost:5432/mnemos_analytics"
    )
    sql_statement_timeout_ms: int = 15_000
    sql_max_rows: int = 5_000
    sql_repair_attempts: int = 2
    # Fernet (`cryptography`). A registered datasource's DSN is stored encrypted
    # at rest (`sql_datasource.dsn_encrypted`) even though the demo warehouse's
    # DSN is itself non-secret — the column exists for a real deployment's
    # credentials, and a registry that only sometimes encrypts is one an
    # operator cannot reason about.
    dsn_encryption_key: SecretStr = SecretStr(DEV_DSN_ENCRYPTION_KEY)

    # -- connectors ---------------------------------------------------------
    # Fernet, same reasoning as `dsn_encryption_key` — a registered
    # `content_source`'s config (a bucket/prefix, a filesystem root, an HTTP
    # allowlist) is stored encrypted at rest, with its own key.
    source_encryption_key: SecretStr = SecretStr(DEV_SOURCE_ENCRYPTION_KEY)
    # The allowlisted root(s) a *deployment operator* has approved for the
    # local-filesystem connector — a second, deployment-time boundary around
    # what any org's `connector register --kind local_fs --root ...` may ever
    # point to. The per-registration `root` alone is not enough: it is
    # supplied by whoever can call the CLI/API for one org, and this setting
    # is the thing that keeps that call from being able to name `/etc` or the
    # container's own root. Empty by default — default-deny, same discipline
    # `allowed_schemas` enforces — so local-fs connectors are refused until an
    # operator opts a real path in.
    local_fs_allowed_roots: list[str] = []

    # -- limits -----------------------------------------------------------
    max_upload_bytes: int = 25 * 1024 * 1024
    chat_history_turns: int = 12

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("database_url", "analytics_database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "must use the asyncpg driver "
                "(postgresql+asyncpg://). A sync driver silently blocks the event loop."
            )
        return v

    @model_validator(mode="after")
    def _reject_the_dev_secret_in_production(self) -> Self:
        """Fail to boot rather than mint forgeable tokens.

        A missing `MNEMOS_JWT_SECRET` in production is indistinguishable from a
        working deployment until somebody signs their own access token with a
        value published in this repository. Checked here, at startup, because
        that is the last moment the failure is cheap (CodingStandards §7).
        """
        if self.env is Environment.PRODUCTION and (
            self.jwt_secret.get_secret_value() == DEV_JWT_SECRET
        ):
            msg = "MNEMOS_JWT_SECRET is still the development default; set a real secret"
            raise ValueError(msg)
        if self.env is Environment.PRODUCTION and (
            self.dsn_encryption_key.get_secret_value() == DEV_DSN_ENCRYPTION_KEY
        ):
            msg = "MNEMOS_DSN_ENCRYPTION_KEY is still the development default; set a real key"
            raise ValueError(msg)
        if self.env is Environment.PRODUCTION and (
            self.source_encryption_key.get_secret_value() == DEV_SOURCE_ENCRYPTION_KEY
        ):
            msg = "MNEMOS_SOURCE_ENCRYPTION_KEY is still the development default; set a real key"
            raise ValueError(msg)
        return self

    @property
    def is_local(self) -> bool:
        return self.env is Environment.LOCAL

    @property
    def refresh_cookie_is_secure(self) -> bool:
        """`Secure` unless this is local development over plain http."""
        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        return self.env is not Environment.LOCAL

    @property
    def refresh_cookie_path(self) -> str:
        """Scoped to the auth routes, so the browser attaches the refresh token
        to the two endpoints that consume it and to nothing else.

        A cookie on `/` rides along on every API call, which widens the blast
        radius of a logging middleware, a proxy that records headers, or a CSRF
        hole in some unrelated endpoint — for a credential only two routes ever
        need."""
        return f"{self.api_prefix}/auth"

    @property
    def web_signin_url(self) -> str:
        """The sign-in screen. Every login failure lands here, with one constant
        flag and no reason (`entrypoints/api/routers/auth.py`)."""
        return f"{self.web_base_url.rstrip('/')}/signin"

    @property
    def web_signin_complete_url(self) -> str:
        """Where a *successful* callback sends the browser.

        The access token is deliberately not carried here. The callback has
        already set the refresh cookie, and the page at this URL exchanges that
        cookie for an access token over `POST /auth/token` — so no credential
        ever appears in a URL, in browser history, or in a `Referer` header.
        """
        return f"{self.web_base_url.rstrip('/')}/signin/complete"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
