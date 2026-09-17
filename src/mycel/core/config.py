"""Configuration read from the environment, once.

Every knob the system needs arrives as an environment variable, so the same image runs in
dev, staging and prod with no `if env == "prod"` anywhere in the code. `.env` is read in
development; in a container the variables are already set.

`extra="ignore"` is load-bearing: `.env.example` carries Postgres, RabbitMQ, Redis, Qdrant and
Slack keys that most entrypoints do not need, and a strict model would refuse to start over
a variable it has no field for.

`get_settings()` is cached — config is read once per process, and tests clear the cache.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every environment variable the system reads, with its default."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    mycel_env: Literal["dev", "staging", "prod"] = "dev"

    # LLM. The cloud key is optional so a local-only run needs no credential at all.
    anthropic_api_key: SecretStr | None = None
    local_llm_base_url: str = "http://localhost:8001/v1"

    # Observability. Disabled by default in development, where no collector is running.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "mycel"

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings. Cached; call `get_settings.cache_clear()` in tests."""
    return Settings()
