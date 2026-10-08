"""Checks that read settings instead of connecting to anything."""

from mycel.core.config import Settings
from mycel.doctor.report import Check, State
from mycel.infra import smtp
from mycel.services import google_oauth, jira_oauth


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
            "REGISTRATION",
            "password reset",
            State.OK if mail_out else State.OFF,
            f"mail from {env.smtp_from} via {env.smtp_host}"
            if mail_out
            else "off — no SMTP, so a forgotten password cannot be reset",
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

    # The one with a default that is wrong as soon as the app is not on a laptop.
    if env.registration_invite_code is None and not env.allowed_domains:
        out.append(
            Check(
                "REGISTRATION",
                "who may sign up",
                State.BROKEN,
                "ANYONE who can reach the URL — set REGISTRATION_INVITE_CODE",
            )
        )
    else:
        how = []
        if env.registration_invite_code is not None:
            how.append("invite code")
        if env.allowed_domains:
            how.append(f"domains: {', '.join(sorted(env.allowed_domains))}")
        out.append(Check("REGISTRATION", "who may sign up", State.OK, " + ".join(how)))

    return out
