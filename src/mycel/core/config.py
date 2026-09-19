"""Configuration read from the environment, once.

Every knob the system needs arrives as an environment variable, so the same image runs in
dev, staging and prod with no `if env == "prod"` anywhere in the code. `.env` is read in
development; in a container the variables are already set.

`extra="ignore"` is load-bearing: `.env.example` carries Postgres, RabbitMQ, Redis, Qdrant and
Slack keys that most entrypoints do not need, and a strict model would refuse to start over
a variable it has no field for.

`get_settings()` is cached — config is read once per process, and tests clear the cache.
"""

from decimal import Decimal
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

    # LLM. Every key is optional: a run needs the one its model spec asks for and no
    # other, so a Gemini-only machine is a valid deployment.
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    local_llm_base_url: str = "http://localhost:8001/v1"

    # Tools that reach outside the process. Optional on the same terms as the model keys:
    # an agent that never searches the web is a valid deployment, and `web_search` says so
    # itself rather than failing at import.
    tavily_api_key: SecretStr | None = None

    # Observability. Agent runs go to Langfuse over OTLP HTTP; the endpoint is derived from
    # the base url, so a deployment sets the two keys and nothing else.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "mycel"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://jp.cloud.langfuse.com"

    # Infrastructure. The broker and the result store both have working defaults pointing
    # at what `docker-compose.yml` brings up, so a dev machine needs neither variable set.
    rabbitmq_url: str = "amqp://mycel:mycel@localhost:5672/"
    redis_url: str = "redis://localhost:6379/0"
    #: How long a finished report stays readable. Long enough for a caller to come back for
    #: it, short enough that Redis is never asked to be a database.
    result_ttl_seconds: int = 3600
    #: Most one queued job may spend. The HTTP layer has its own ceiling in
    #: `api/dependencies.py`; a worker has no request to read one from, so it reads this.
    job_ceiling_usd: Decimal = Decimal("0.50")

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings. Cached; call `get_settings.cache_clear()` in tests."""
    return Settings()
