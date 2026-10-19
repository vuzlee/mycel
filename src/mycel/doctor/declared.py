"""Checks that read settings instead of connecting to anything."""

from mycel.core.config import Settings
from mycel.doctor.report import Check, State
from mycel.infra import smtp
from mycel.services import google_oauth, jira_oauth

#: Values shipped in .env.example; a prod deployment still holding one is open to anyone.
DEV_VALUES = {
    "litellm_api_key": "sk-mycel-dev",
    "s3_secret_key": "mycel-dev-secret",
    "database_url": "postgresql://mycel:mycel@",
    "rabbitmq_url": "amqp://mycel:mycel@",
}


def dev_values(env: Settings) -> list[str]:
    """Which settings still hold a value from .env.example."""

    def raw(name: str) -> str:
        value = getattr(env, name)
        return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value or "")

    return [n.upper() for n, dev in DEV_VALUES.items() if raw(n).startswith(dev)]


def declared(env: Settings) -> list[Check]:
    """Things that are settings rather than connections."""
    out: list[Check] = []

    out.append(
        Check(
            "TOOLS",
            "web search",
            State.OK if env.tavily_api_key else State.OFF,
            "key set" if env.tavily_api_key else "not configured — web_search is not offered",
        )
    )
    mail_out = smtp.configured(env)
    out.append(
        Check(
            "SIGN-IN",
            "emailed code",
            State.OK if mail_out else State.OFF,
            f"mail from {env.smtp_from} via {env.smtp_host}"
            if mail_out
            else "off — no SMTP, so only Google sign-in works",
        )
    )
    configured = google_oauth.configured(env)
    out.append(
        Check(
            "TOOLS",
            "calendar & mail",
            State.OK if configured else State.OFF,
            "per-user OAuth ready — each person's own calendar and mail"
            if configured
            else "not configured — the calendar and mail tools are not offered",
        )
    )
    # Two switches, and off is a decision rather than a gap.
    writes = jira_oauth.configured(env) and env.jira_write_enabled
    out.append(
        Check(
            "TOOLS",
            "jira writes",
            State.OK if writes else State.OFF,
            (
                "on, as whoever is asking"
                + (" — including create_project" if env.jira_allow_create_project else "")
            )
            if writes
            else "off — the Jira write tools are not offered",
        )
    )

    if not mail_out and not google_oauth.configured(env):
        out.append(
            Check(
                "SIGN-IN", "any way in", State.BROKEN, "no SMTP and no Google — nobody can sign in"
            )
        )
    left = dev_values(env)
    if env.mycel_env == "prod" and left:
        out.append(
            Check("SECRETS", "dev values", State.BROKEN, f"still the dev value: {', '.join(left)}")
        )

    # The one with a default that is wrong as soon as the app is not on a laptop.
    domains = env.allowed_domains
    out.append(
        Check(
            "SIGN-IN",
            "who may sign in",
            State.OK if domains else State.BROKEN,
            f"domains: {', '.join(sorted(domains))}"
            if domains
            else "ANY Google account or mailbox — set REGISTRATION_ALLOWED_DOMAINS",
        )
    )

    return out
