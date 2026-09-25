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

from pydantic import SecretStr, model_validator
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
    #
    # Plural for Gemini only, because several keys for one provider are several accounts
    # and so several free tiers — see `llm/keyring.py`, and Gemini's is the quota this
    # project actually runs into. The singular names below still work and count as a list
    # of one, so no deployment has to change to keep running. Anthropic has no plural form:
    # no agent asks for that provider, and an environment variable for something nothing
    # reads is a promise the code does not keep.
    gemini_api_keys: str = ""
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
    #: Which custom field holds the sprint. Jira numbers custom fields per site, so
    #: there is no id that is right everywhere — this default is Atlassian's usual one for
    #: a cloud site, and a site that differs sets it rather than being unable to use the
    #: feature. The sync asks for it by id and skips it silently when the site has none.
    jira_sprint_field: str = "customfield_10020"
    #: Whether this deployment may write back to Jira. Off by default: reading someone's
    #: tracker is recoverable and commenting on fifty issues by mistake is not, so a write
    #: path that exists has to be switched on deliberately.
    jira_write_enabled: bool = False

    # Outputs. One-way and optional: a deployment with nothing configured still works, and
    # `notify/` logs a missing credential rather than failing the job that produced the
    # thing it was going to send.
    #: Where a link out of this deployment points. Nothing has no page to be relative to,
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

    def llm_keys(self, provider: str) -> list[str]:
        """Every key configured for one provider, in the order they were written.

        Only Gemini has a plural form, and it wins when both are set, because one place to
        declare a thing is the point of adding it; the singular is read only when the plural
        is empty.
        """
        if provider == "google":
            keys = [part.strip() for part in self.gemini_api_keys.split(",") if part.strip()]
            if keys:
                return keys
        single = {"google": self.gemini_api_key, "anthropic": self.anthropic_api_key}[provider]
        return [single.get_secret_value()] if single is not None else []

    @model_validator(mode="after")
    def _warn_on_both_key_forms(self) -> "Settings":
        """Say so when Gemini has keys under both names.

        Silently picking one of two declarations is where somebody loses an afternoon, and
        `frozen=True` means this is the last moment anything can say anything about it.
        """
        from mycel.core.logging import get_logger

        if self.gemini_api_keys.strip() and self.gemini_api_key is not None:
            get_logger(__name__).warning(
                "both key forms are set; the plural one is used",
                extra={"used": "GEMINI_API_KEYS", "ignored": "GEMINI_API_KEY"},
            )
        return self

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
    #: Most one queued job may spend. The HTTP layer has its own ceiling in
    #: `api/dependencies.py`; a worker has no request to read one from, so it reads this.
    job_ceiling_usd: Decimal = Decimal("0.50")

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings. Cached; call `get_settings.cache_clear()` in tests."""
    return Settings()
