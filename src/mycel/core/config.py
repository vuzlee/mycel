"""Settings from the environment, `.env` and `config/environments/` YAML, read once.

`extra="ignore"` because `.env` also carries container-only variables with no field here.
"""

from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, SecretStr, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from mycel.core.settings_source import EnvironmentFileSource


class HostModel(BaseModel):
    """One model the host offers to everyone, by its LiteLLM `model_name`."""

    name: str
    label: str
    default: bool = False


class Settings(BaseSettings):
    """Every setting. Secrets live in `.env`; everything committable lives in `config/`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Sources, highest priority first: init, environment, .env, YAML, secrets."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            EnvironmentFileSource(settings_cls),
            file_secret_settings,
        )

    mycel_env: Literal["dev", "staging", "prod"] = "dev"

    # Every model goes through the LiteLLM gateway; provider keys are read by it, not the app.
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: SecretStr | None = None
    #: USD per million tokens, (input, output), by gateway model name.
    model_prices_usd: dict[str, tuple[Decimal, Decimal]] = {}
    #: The models everyone may pick, each a gateway `model_name`; exactly one is the default.
    host_models: tuple[HostModel, ...] = (
        HostModel(name="claude-sonnet-5", label="Claude Sonnet 5", default=True),
    )
    #: Hosts an own model may reach over plain http (a LAN Ollama); others need https.
    model_http_hosts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _one_default_model(self) -> "Settings":
        defaults = [m.name for m in self.host_models if m.default]
        if len(defaults) != 1:
            raise ValueError(f"host_models needs exactly one default, found {defaults or 'none'}")
        if len({m.name for m in self.host_models}) != len(self.host_models):
            raise ValueError("host_models lists a name twice")
        return self

    @property
    def default_host_model(self) -> HostModel:
        """The model a person gets before choosing one."""
        return next(m for m in self.host_models if m.default)

    tavily_api_key: SecretStr | None = None

    #: The background sync's Atlassian service account token (never a person's).
    jira_service_token: SecretStr | None = None
    jira_cloud_id: str | None = None
    #: The service token's last day (Atlassian does not return it); `doctor` warns early.
    jira_service_token_expires: date | None = None
    #: Atlassian OAuth 3LO app; callback `{public_base_url}/auth/jira/callback`.
    jira_client_id: str | None = None
    jira_client_secret: SecretStr | None = None
    #: Whether writing back to Jira is offered at all.
    jira_write_enabled: bool = False
    #: Whether creating a project is offered; separate because it cannot be undone.
    jira_allow_create_project: bool = False
    #: Whether the Jira grant can manage sprints; only the board maintenance scripts use it.
    jira_manage_sprints: bool = False

    #: This deployment's own address, for outbound links.
    public_base_url: str = "http://localhost:8000"
    #: Google OAuth web client; redirect `{public_base_url}/auth/google/callback`.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    #: Fernet key encrypting stored refresh tokens. Unset refuses to connect accounts.
    token_encryption_key: SecretStr | None = None
    sync_interval_seconds: int = 900
    timezone: str = "UTC"
    session_sweep_interval_seconds: int = 86400

    smtp_host: str | None = None
    smtp_port: int = 587
    #: The From address; required together with the host.
    smtp_from: str | None = None
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True

    #: Comma-separated email domains that may have an account; empty allows any.
    registration_allowed_domains: str = ""

    @property
    def allowed_domains(self) -> frozenset[str]:
        """The allowlist, lowercased and split. Empty means every domain."""
        parts = self.registration_allowed_domains.split(",")
        return frozenset(p.strip().lower().lstrip("@") for p in parts if p.strip())

    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "mycel"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    #: Whether spans carry prompt and reply text (sends user data to a third party).
    otel_capture_content: bool = False
    #: `/metrics` interface; it has no auth, so binding is the only access control.
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9100

    #: The app's connection (`mycel_app` in deployments: no DDL rights).
    database_url: str = "postgresql://mycel:mycel@localhost:5433/mycel"
    #: The schema owner for migrations; unset falls back to `database_url`.
    migration_database_url: str | None = None
    #: `mycel_app`'s password; unset, the role is not created.
    mycel_app_password: SecretStr | None = None
    #: Per process, so the real ceiling is this times the process count.
    db_pool_size: int = 5
    #: Extra connections opened under a burst, closed when idle.
    db_max_overflow: int = 5
    rabbitmq_url: str = "amqp://mycel:mycel@localhost:5672/"
    #: In-flight state (results, budgets, event streams), on a `noeviction` server.
    redis_url: str = "redis://localhost:6379/0"
    #: Evictable cache (answers, access tokens), on its own `allkeys-lru` server.
    redis_cache_url: str = "redis://localhost:6380/0"
    #: Connections per client; each open SSE stream holds one while it blocks on a read.
    redis_max_connections: int = 500
    #: How long a call waits for a free connection before it fails.
    redis_pool_timeout_seconds: float = 5.0
    #: Off only for a load test: login, signup, reset and chat are capped per minute.
    rate_limits_enabled: bool = True
    #: How long a finished answer stays readable.
    result_ttl_seconds: int = 3600
    #: Events kept per job stream; a lagging client sees a gap in `seq`.
    event_stream_max_events: int = 1000
    #: How long a job's event stream lives: only for a reconnect, shorter than the result.
    event_stream_ttl_seconds: int = 900

    #: Empty disables search, and `rag_search` is not offered.
    qdrant_url: str = ""
    #: Part of the collection name: changing it needs a new collection and a reindex.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    #: Where fastembed keeps downloaded weights; mount it in containers.
    embedding_cache_dir: str = ".cache/fastembed"

    s3_endpoint_url: str = ""
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    documents_bucket: str = "mycel-documents"
    document_embedding_model: str = "jinaai/jina-embeddings-v2-small-en"
    document_chunk_tokens: int = 500
    document_table_max_tokens: int = 1500
    document_max_bytes: int = 2 * 1024 * 1024
    document_max_pages: int = 100
    documents_per_user: int = 200
    documents_in_flight_per_user: int = 5
    document_stuck_seconds: int = 600
    ingest_worker_max_jobs: int = 20
    #: How long a stopping worker waits for its jobs; under the pod's grace period.
    worker_drain_seconds: float = 50
    ingest_threads: int = 2
    document_min_score: float = 0.68
    ask_top_k: int = 5
    ask_max_chars: int = 500
    #: Most one queued job may spend.
    job_ceiling_usd: Decimal = Decimal("0.50")
    #: Most one person's chat may spend in 24 hours, counting open jobs at their ceiling. 0: off.
    user_daily_usd: Decimal = Decimal("5.00")

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings. Cached; call `get_settings.cache_clear()` in tests."""
    return Settings()


def zone_of(name: object) -> ZoneInfo:
    """A browser's IANA zone name, or UTC when it is missing or not one the system knows."""
    if isinstance(name, str) and name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo("UTC")


def team_zone() -> ZoneInfo:
    """The team's zone, falling back to UTC if the name is not one the system knows."""
    try:
        return ZoneInfo(get_settings().timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")
