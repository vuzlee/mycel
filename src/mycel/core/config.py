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

    # Sources. A deployment syncs the providers it has credentials for; a missing token
    # is not an error until something actually asks that source for data.
    #: Jira is the source of record for what the work *is*. Basic auth with a personal
    #: API token, which expires exactly one year after it is issued.
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None
    #: Which project to sync. Empty means every project the account can see, which is
    #: right for a one-project site and wrong for a shared one.
    jira_project_key: str | None = None
    #: Telegram is no longer a source: the bot sends notifications and reads nothing.
    telegram_bot_token: SecretStr | None = None
    telegram_notify_chat_id: str | None = None

    # Outputs. Both one-way, both optional: a deployment with neither still works, and
    # `notify/` logs a missing credential rather than failing the job that produced the
    # thing it was going to send.
    #: Where a notification's link points. A chat message has no page to be relative to,
    #: so this is the only place the deployment's own address is written down.
    public_base_url: str = "http://localhost:8000"
    #: The calendar due dates are written to. Give it one of its own — a bug then writes
    #: junk into a calendar nobody keeps by hand.
    google_calendar_id: str | None = None
    #: Path to a service-account key file, kept outside the repo. Note 015's per-user
    #: OAuth is a different mechanism for a different question; this one is the
    #: deployment writing to its own calendar, and needs no user to be present.
    google_service_account_json: str | None = None
    #: Seconds between scheduled syncs. Jira keeps its history, so this is a freshness
    #: knob rather than a deadline — nothing is lost by syncing late.
    sync_interval_seconds: int = 900

    #: The mailbox `agents/tools/mail.py` reads headers from, over IMAP. An app password
    #: is a full-access password with no narrower scope available, which is why the
    #: headers-only discipline is enforced in the IMAP fetch string rather than here.
    gmail_address: str | None = None
    gmail_app_password: SecretStr | None = None

    # Observability. Agent runs go to Langfuse over OTLP HTTP; the endpoint is derived from
    # the base url, so a deployment sets the two keys and nothing else.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "mycel"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://jp.cloud.langfuse.com"

    # Infrastructure. The defaults are the throwaway local ones `docker-compose.yml`
    # brings up, so a dev machine needs neither variable set. Any deployment that is not
    # a laptop overrides both from the environment — there is no real password here.
    #: Read by both the engine and alembic. Stored as the plain `postgresql://` form the
    #: rest of the world writes; `postgres/engine.py` swaps in the async driver.
    database_url: str = "postgresql://mycel:mycel@localhost:5432/mycel"
    #: Pool size is per process. `api` runs N uvicorn workers and `worker` scales by
    #: consumer count, so the ceiling that matters is this times the process count.
    db_pool_size: int = 5
    rabbitmq_url: str = "amqp://mycel:mycel@localhost:5672/"
    #: In-flight state: results, budgets, event streams. This server runs `noeviction` —
    #: see `infra/redis/client.py`.
    redis_url: str = "redis://localhost:6379/0"
    #: Cached values, on a server that is allowed to evict them. A separate db index by
    #: default, so the two policies never share a keyspace.
    redis_cache_url: str = "redis://localhost:6379/1"
    #: How long a finished report stays readable. Long enough for a caller to come back for
    #: it, short enough that Redis is never asked to be a database.
    result_ttl_seconds: int = 3600
    #: How many events one job's stream keeps. Capped so a chatty run cannot fill Redis;
    #: a client that falls this far behind sees a gap in `seq` and knows it.
    event_stream_max_events: int = 1000
    #: Most one queued job may spend. The HTTP layer has its own ceiling in
    #: `api/dependencies.py`; a worker has no request to read one from, so it reads this.
    job_ceiling_usd: Decimal = Decimal("0.50")

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings. Cached; call `get_settings.cache_clear()` in tests."""
    return Settings()
