"""Application settings for ClaimGuard, loaded from the environment.

Every variable is read from the environment with the ``CLAIMGUARD_`` prefix
(``CLAIMGUARD_DATABASE_URL``, ``CLAIMGUARD_LLM_MODEL``, ...) and may also be
provided through a ``.env`` file next to the repository root. Settings are
immutable and cached; use :func:`get_settings` everywhere instead of
instantiating :class:`Settings` directly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration for ClaimGuard (env-first, immutable)."""

    model_config = SettingsConfigDict(
        env_prefix="CLAIMGUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- database ----------------------------------------------------------
    # SQLAlchemy URL; the Alembic env (claimguard/db/migrations/env.py) reads
    # this to run migrations. Uses the psycopg3 driver (sync and async alike).
    database_url: str = "postgresql+psycopg://claimguard_app@localhost:5432/claimguard"

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""
    # Temperature 0.0 by default: pre-validation is a deterministic copilot,
    # never a creative rewrite (see docs/04 §12).
    llm_temperature: float = 0.0

    # --- observability -----------------------------------------------------
    # OpenTelemetry OTLP/HTTP endpoint (docker-otel-lgtm exposes :4318).
    otel_endpoint: str = "http://localhost:4318"
    otel_service_name: str = "claimguard"
    # Gates the optional P1 telemetry wiring: off by default so no SDK provider
    # is registered and no network call is made unless an operator opts in.
    ops_otel_enabled: bool = False
    # P2 operations console sources. The backend is the only client of these;
    # inside Docker Compose they are the otel-lgtm service ports:
    #   CLAIMGUARD_OPS_METRICS_URL=http://otel-lgtm:9090
    #   CLAIMGUARD_OPS_TRACES_URL=http://otel-lgtm:3200
    ops_metrics_url: str = "http://localhost:9090"
    ops_traces_url: str = "http://localhost:3200"
    ops_source_timeout_seconds: float = 2.0

    # --- runtime -----------------------------------------------------------
    log_level: str = "INFO"
    environment: str = "development"

    # --- durable execution (Temporal, thin and optional — see ADR-010) -----
    temporal_address: str = "localhost:7233"
    temporal_enabled: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance (single source of truth)."""

    return Settings()
