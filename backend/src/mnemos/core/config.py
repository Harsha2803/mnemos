"""Application settings.

Validated once at startup and failed fast. A service that boots with malformed
configuration and discovers it on the first request is a service that fails in
production rather than in CI.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


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
    jwt_secret: SecretStr = SecretStr("dev-only-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 60 * 60 * 24 * 14

    # Split-horizon OIDC. The browser is redirected to the public issuer; the API
    # fetches JWKS over the internal one. Collapsing these into a single URL is
    # the standard containerised-OIDC failure: the token's `iss` never matches
    # what the API expects.
    oidc_enabled: bool = True
    oidc_issuer_public: str = "http://localhost:8080/realms/mnemos"
    oidc_issuer_internal: str = "http://localhost:8080/realms/mnemos"
    oidc_client_id: str = "mnemos-web"
    oidc_jwks_cache_s: int = 900

    # -- context compiler defaults ---------------------------------------
    default_token_budget: int = 3000
    default_operator_deadline_ms: int = 2000
    rrf_k: int = 60
    near_duplicate_threshold: float = Field(default=0.86, ge=0.0, le=1.0)
    utility_decay_tau: float = Field(default=6.0, gt=0.0)

    # -- nl2sql -----------------------------------------------------------
    # Separate database, read-only role. The AST guard is the second line of
    # defence, not the only one.
    analytics_database_url: str = (
        "postgresql://mnemos_ro:mnemos_ro_dev@localhost:5432/mnemos_analytics"
    )
    sql_statement_timeout_ms: int = 15_000
    sql_max_rows: int = 5_000
    sql_repair_attempts: int = 2

    # -- limits -----------------------------------------------------------
    max_upload_bytes: int = 25 * 1024 * 1024
    chat_history_turns: int = 12

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "database_url must use the asyncpg driver "
                "(postgresql+asyncpg://). A sync driver silently blocks the event loop."
            )
        return v

    @property
    def is_local(self) -> bool:
        return self.env is Environment.LOCAL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
