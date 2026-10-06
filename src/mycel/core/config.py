"""Configuration read from the environment, once.

Every knob the system needs arrives as an environment variable, so the same image runs in
dev, staging and prod with no `if env == "prod"` anywhere in the code. `.env` is read in
development; in a container the variables are already set.

`extra="ignore"` is load-bearing: `.env.example` carries the Postgres, RabbitMQ and Redis
credentials the containers read and no field here does, and a strict model would refuse to
start over a variable it has no field for.

`get_settings()` is cached — config is read once per process, and tests clear the cache.
"""

from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from mycel.core.settings_source import EnvironmentFileSource


class Settings(BaseSettings):
    """Every setting the system reads, wherever it comes from.

    Four sources, and later wins:

        class default  <  config/environments/*.yaml  <  .env  <  environment

    The split between the last two and the rest is one rule: **what must never reach git
    lives in `.env`, everything else lives in `config/`.** Keys, passwords and the four
    store URLs stay; intervals, hosts, log levels and feature switches move.

    The store URLs look like the exception and are not: `postgresql://user:pw@host/db` is a
    password with an address attached, and a committed one is a committed password.

    **The environment wins, always.** `docker run -e LOG_LEVEL=DEBUG` has to work, or
    environment variables stop meaning anything — see `settings_source.py`.
    """

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
        """The four sources, highest priority first.

        pydantic-settings reads this tuple in order and the FIRST source to supply a name
        wins, which is the reverse of how the docstring above reads it. Written
        highest-first here because that is the order pydantic wants; read it as "init beats
        environment beats .env beats YAML beats the class default".
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            EnvironmentFileSource(settings_cls),
            file_secret_settings,
        )

    mycel_env: Literal["dev", "staging", "prod"] = "dev"

    # LLM. Every model is reached through the LiteLLM gateway (`config/litellm/`). The
    # provider keys live in `.env` and are read by the gateway, never by the app.
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: SecretStr | None = None
    #: USD per million tokens, (input, output), by gateway model name.
    model_prices_usd: dict[str, tuple[Decimal, Decimal]] = {}

    # Tools that reach outside the process. Optional on the same terms as the model keys:
    # an agent that never searches the web is a valid deployment, and `web_search` says so
    # itself rather than failing at import.
    tavily_api_key: SecretStr | None = None

    # Sources. A deployment syncs the providers it has credentials for; a missing token
    # is not an error until something actually asks that source for data.
    #: Jira is the source of record for what the work *is*. The base url is not a secret:
    #: the site is public and the consent is what is not.
    jira_base_url: str | None = None
    #: The background sync's own identity: an Atlassian service account with Browse on
    #: the projects to sync, and its API token. Never a person's token — a sync that runs
    #: on someone stops when they leave. Every project it can browse is synced.
    jira_service_token: SecretStr | None = None
    jira_cloud_id: str | None = None
    #: The service token's last day. Atlassian does not return it, so it is written down
    #: when the token is made; `doctor` warns a month before.
    jira_service_token_expires: date | None = None
    #: The Atlassian OAuth 2.0 (3LO) app a person consents to, so Mycel can ask Jira which
    #: projects *they* may browse and write as them. developer.atlassian.com -> your app ->
    #: Authorization, with `{public_base_url}/auth/jira/callback` as a callback URL.
    jira_client_id: str | None = None
    jira_client_secret: SecretStr | None = None
    #: Whether this deployment may write back to Jira. Off by default: reading someone's
    #: tracker is recoverable and commenting on fifty issues by mistake is not, so a write
    #: path that exists has to be switched on deliberately.
    jira_write_enabled: bool = False
    #: Whether creating a Jira *project* is offered. Its own switch, separate from the one
    #: above, because the three other writes can be undone and this one cannot: many sites
    #: refuse to delete a project over the API, and a project key is never reusable. On, and
    #: the consent screen asks for `manage:jira-project` as well; off, and it never does.
    jira_allow_create_project: bool = False

    # Outputs. One-way and optional: a deployment with nothing configured still works, and
    # `notify/` logs a missing credential rather than failing the job that produced the
    # thing it was going to send.
    #: Where a link out of this deployment points. Nothing has no page to be relative to,
    #: so this is the only place the deployment's own address is written down.
    public_base_url: str = "http://localhost:8000"
    #: The OAuth client a person consents to, so Mycel may read and write *their* calendar.
    #: A client rather than a service account: a service account writes to a calendar of
    #: the deployment's own, which is the wrong calendar for "what have I got this
    #: afternoon". Console -> APIs & Services -> Credentials -> OAuth client ID, type
    #: "Web application", with `{public_base_url}/auth/google/callback` as a redirect URI.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    #: The key every stored refresh token is encrypted with — Google's and Atlassian's
    #: alike. Url-safe base64, 32 bytes:
    #: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    #: No default and no fallback to plaintext — a refresh token opens one person's account
    #: for as long as they leave it alone, so a deployment without this key refuses to
    #: connect an account rather than keeping one readably. Named for what it does rather
    #: than for one of its two users: it was `GOOGLE_TOKEN_KEY` until batch 060 gave it a
    #: second.
    token_encryption_key: SecretStr | None = None
    #: Seconds between scheduled syncs. Jira keeps its history, so this is a freshness
    #: knob rather than a deadline — nothing is lost by syncing late.
    sync_interval_seconds: int = 900
    #: The team's own timezone, as an IANA name. A Jira due date is a bare calendar day
    #: with no zone, and "end of that day" only means anything in a zone: read as UTC, a
    #: UTC+7 team's overdue work still counts as on time until seven the next morning.
    timezone: str = "UTC"
    #: How often expired sessions are swept. Nothing depends on it — expiry is checked on
    #: read — but without it `app.session` only ever grows.
    session_sweep_interval_seconds: int = 86400

    # Sending mail. The only channel that reaches a person, and the reason a forgotten
    # password can be recovered at all: without it `/auth/forgot` answers the same way but
    # nothing arrives, so the route refuses instead of pretending.
    smtp_host: str | None = None
    smtp_port: int = 587
    #: The From address. Set together with the host — a message with no sender is refused
    #: by every server worth sending through.
    smtp_from: str | None = None
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    #: STARTTLS on the usual submission port. Off only for a local capture server in a
    #: test, never for anything that leaves the machine.
    smtp_starttls: bool = True
    #: How long a reset link works. Short: it is a password in an inbox, and an inbox is
    #: read by whoever is sitting at the machine.
    password_reset_ttl_seconds: int = 3600

    # Who may create an account. Both empty means registration is open, which is right for
    # one machine on localhost and wrong for anything reachable from outside it.
    #: Comma-separated email domains that may register, e.g. "acme.com,acme.vn". Set, and
    #: an address outside them is refused.
    registration_allowed_domains: str = ""
    #: A shared code the registration form must carry. Set, and a request without it is
    #: refused. Coarse — one code for everyone, rotated by changing it — but it is the
    #: difference between a gate and no gate.
    registration_invite_code: SecretStr | None = None

    @property
    def allowed_domains(self) -> frozenset[str]:
        """The allowlist, lowercased and split. Empty means every domain."""
        parts = self.registration_allowed_domains.split(",")
        return frozenset(p.strip().lower().lstrip("@") for p in parts if p.strip())

    # Observability. Agent runs go to Langfuse over OTLP HTTP; the endpoint is derived from
    # the base url, so a deployment sets the two keys and nothing else.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "mycel"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://jp.cloud.langfuse.com"
    #: Whether a span carries the prompt sent and the text returned, as well as the model,
    #: tokens and cost it always carries. Off by default because turning it on sends real
    #: user data to a third party: the question somebody typed, and the internal figures
    #: that came back. On in development, where reading the SQL an agent wrote is the
    #: whole point of having a trace; off in production unless somebody has decided.
    otel_capture_content: bool = False
    #: Where `/metrics` listens in the worker and the scheduler. The api serves it on the
    #: port it already has. Loopback by default: the endpoint has no authentication, so
    #: the interface it binds to is the only thing making it private.
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9100

    # Infrastructure. The defaults are the throwaway local ones `docker-compose.yml`
    # brings up, so a dev machine needs neither variable set. Any deployment that is not
    # a laptop overrides both from the environment — there is no real password here.
    #: Read by both the engine and alembic. Stored as the plain `postgresql://` form the
    #: rest of the world writes; `postgres/engine.py` swaps in the async driver.
    database_url: str = "postgresql://mycel:mycel@localhost:5433/mycel"
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
    #: How long a finished answer stays readable. Long enough for a caller to come back for
    #: it, short enough that Redis is never asked to be a database.
    result_ttl_seconds: int = 3600
    #: How many events one job's stream keeps. Capped so a chatty run cannot fill Redis;
    #: a client that falls this far behind sees a gap in `seq` and knows it.
    event_stream_max_events: int = 1000

    # Search over gold. Optional on the same terms as the model keys: a deployment without
    # Qdrant running is valid, and `rag_search` says so itself rather than failing at
    # import — see `agents/tools/rag_search.py`.
    #
    #: Where Qdrant answers. Empty disables search entirely rather than leaving a tool that
    #: fails on every call: a tool the model can see is a tool it will try.
    qdrant_url: str = ""
    #: The embedding model, run on this machine. Its name is part of the collection name,
    #: because the dimension belongs to the model: changing it means a new collection and a
    #: full reindex, and there is no way to mix two vector spaces in one.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    #: Where fastembed keeps the downloaded ONNX weights. Named so a container can mount it
    #: and not re-download 130 MiB on every start.
    embedding_cache_dir: str = ".cache/fastembed"

    # Notebooks: uploaded documents, chunked and embedded for question answering.
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
    document_max_attempts: int = 3
    document_stuck_seconds: int = 600
    ingest_worker_max_jobs: int = 20
    document_min_score: float = 0.75
    ask_per_user_daily: int = 10
    ask_system_daily: int = 10
    ask_top_k: int = 5
    ask_max_chars: int = 500
    #: Most one queued job may spend. The HTTP layer has its own ceiling in
    #: `api/dependencies.py`; a worker has no request to read one from, so it reads this.
    job_ceiling_usd: Decimal = Decimal("0.50")

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings. Cached; call `get_settings.cache_clear()` in tests."""
    return Settings()
