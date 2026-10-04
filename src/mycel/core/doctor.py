"""What is configured, what is broken, and what is off on purpose.

The three states are the point, and the value is in telling the last two apart. An absent
`rag_search` looks exactly like a broken one from outside, and somebody who has just cloned
the repo cannot tell whether to go fixing or to relax.

    OK       it answered
    BROKEN   configured, and it did not answer
    OFF      not configured — the feature it belongs to is simply not there

**Nothing here writes.** No table, no file, no edit to `.env`. That is also why this beats a
setup screen for an app whose operator has a shell: a screen has to store what it collects,
and storing means configuration lives in two places that can disagree.

Every probe has a short timeout and swallows its own failure. A doctor that hangs on a dead
host, or dies on the first one, is a doctor nobody runs twice.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from mycel.core.config import Settings


class State(StrEnum):
    OK = "ok"
    BROKEN = "broken"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class Check:
    """One line of the report."""

    group: str
    name: str
    state: State
    detail: str


#: Long enough for a local container, short enough that a wrong host does not look like a
#: hang. A doctor is something people run while deciding whether to wait.
TIMEOUT = 3.0

#: For anything across the internet. Three seconds is right for a container on this machine
#: and wrong for Atlassian: a healthy Jira answering in four would be reported BROKEN, which
#: is the one mistake this file must not make — a false alarm costs more than a slow report.
REMOTE_TIMEOUT = 15.0


async def _probe(
    name: str,
    group: str,
    probe: Callable[[], Awaitable[str]],
    *,
    missing: str | None,
    timeout: float = TIMEOUT,
) -> Check:
    """Run one probe, or report why it was not run.

    `missing` is the sentence for a feature that is not configured: present means OFF, and
    the probe is never attempted. That distinction is the whole file.

    Takes a CALLABLE rather than a coroutine, and that is not style. A coroutine built at
    the call site is built whether or not it is awaited — so an OFF check left one hanging
    unawaited, which Python reports as a RuntimeWarning from somewhere unrelated. A
    callable is not called at all.
    """
    if missing is not None:
        return Check(group, name, State.OFF, missing)
    try:
        detail = await asyncio.wait_for(probe(), timeout=timeout)
        return Check(group, name, State.OK, detail)
    except TimeoutError:
        return Check(group, name, State.BROKEN, f"no answer in {timeout:.0f}s")
    except Exception as exc:
        # The class name as well as the message: an empty OSError says nothing, and
        # "ConnectionRefusedError" alone is usually enough to know what to do.
        message = str(exc).strip() or type(exc).__name__
        return Check(group, name, State.BROKEN, message.splitlines()[0][:90])


async def _postgres(settings: Settings) -> str:
    from sqlalchemy import text

    from mycel.infra.postgres.session import session_scope

    async with session_scope() as session:
        count = await session.scalar(
            text("select count(*) from information_schema.tables "
                 "where table_schema in ('bronze','silver','gold','app')")
        )
    return f"connected, {count} tables"


async def _rabbitmq(settings: Settings) -> str:
    import aio_pika

    connection = await aio_pika.connect_robust(settings.rabbitmq_url, timeout=TIMEOUT)
    await connection.close()
    return "connected"


async def _redis(settings: Settings) -> str:
    import redis.asyncio as redis

    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
        policy = (await client.config_get("maxmemory-policy")).get("maxmemory-policy", "?")
    finally:
        await client.aclose()
    # noeviction is load-bearing: an evicted budget reads back as a full ceiling, which
    # silently refunds a job. Worth saying out loud rather than only in a docstring.
    if policy != "noeviction":
        return f"connected, but policy is {policy} — an evicted budget refunds a job"
    return "connected, noeviction"


async def _qdrant(settings: Settings) -> str:
    from mycel.infra.vectors import collections
    from mycel.infra.vectors.client import client

    name = collections.work_items(settings.embedding_model).name
    if not await client().collection_exists(name):
        return "connected, nothing indexed yet"
    count = await client().count(name)
    return f"connected, {count.count} points"


async def _minio(settings: Settings) -> str:
    from mycel.infra.objects.client import s3

    async with s3() as client:
        buckets = (await client.list_buckets()).get("Buckets", [])
    names = {b["Name"] for b in buckets}
    if settings.documents_bucket not in names:
        return "connected, no documents uploaded yet"
    return f"connected, bucket {settings.documents_bucket}"


async def _parser(settings: Settings) -> str:
    """Whether this machine can run the ingest worker at all."""
    import importlib.util

    if importlib.util.find_spec("docling") is None:
        raise RuntimeError("docling is not installed — uv sync --extra ingest")
    return f"docling installed; embedding with {settings.document_embedding_model}"


async def _jira(settings: Settings) -> str:
    """Whether a sync can actually run, which is a question about a person now.

    Jira is read on one person's consent — the syncer's. So "is Jira configured" is no
    longer enough: a deployment with a client, a key and nobody connected is one where
    every tick fails and the dashboard quietly ages. The answer names who holds the role
    and when they last succeeded, because that is the only way to tell a syncer who left
    from a week in which nothing happened.
    """
    from mycel.services.jira_oauth import syncer, syncer_token
    from mycel.sources import jira

    who = await syncer()
    if who is None:
        raise RuntimeError(
            "nobody has connected Jira — no sync can run. The first person to connect in "
            "Settings becomes the syncer."
        )

    token, cloud_id, _ = await syncer_token()
    jql = f"project = {settings.jira_project_key} ORDER BY created DESC"
    issues = await jira.search_issues(jira.Auth(token, cloud_id), jql)
    last = who.last_sync_at.strftime("%Y-%m-%d %H:%M") if who.last_sync_at else "never"
    return (
        f"{len(issues)} issues in {settings.jira_project_key}; "
        f"syncing as {who.display_name}, last sync {last}"
    )


async def _langfuse(settings: Settings) -> str:
    return f"keys set, sending to {settings.langfuse_base_url}"


async def run(settings: Settings | None = None) -> list[Check]:
    """Every check, concurrently. Returns the report rather than printing it."""
    env = settings or Settings()

    jobs = [
        _probe("postgres", "STORES", lambda: _postgres(env), missing=None),
        _probe("rabbitmq", "STORES", lambda: _rabbitmq(env), missing=None),
        _probe("redis", "STORES", lambda: _redis(env), missing=None),
        _probe(
            "jira", "SOURCES", lambda: _jira(env),
            missing=None if (env.jira_client_id and env.jira_client_secret and env.jira_project_key)
            else "not configured — the dashboard will be empty",
            timeout=REMOTE_TIMEOUT,
        ),
        _probe(
            "qdrant", "SEARCH", lambda: _qdrant(env),
            missing=None if env.qdrant_url.strip()
            else "not configured — rag_search is not offered to the model",
        ),
        _probe(
            "minio", "NOTEBOOKS", lambda: _minio(env),
            missing=None if (env.s3_endpoint_url and env.s3_access_key and env.s3_secret_key)
            else "not configured — notebooks cannot store uploads",
        ),
        _probe("ingest", "NOTEBOOKS", lambda: _parser(env), missing=None),
        _probe(
            "langfuse", "OBSERVABILITY", lambda: _langfuse(env),
            missing=None if (env.langfuse_public_key and env.langfuse_secret_key)
            else "not configured — the app runs, nothing records what it did",
        ),
    ]
    checks = list(await asyncio.gather(*jobs))

    # Not probes: nothing to connect to, but the answer is what somebody wants to know.
    checks.extend(_declared(env))
    return checks


def _declared(env: Settings) -> list[Check]:
    """Things that are settings rather than connections.

    `models` is a count, not a call: asking a provider whether a key works costs a request
    from a free tier of twenty a day, and the common failure is an absent key rather than
    an invalid one.
    """
    out: list[Check] = []

    keys = env.llm_keys("google")
    out.append(
        Check("MODELS", "gemini", State.OK if keys else State.BROKEN,
              f"{len(keys)} key(s), one quota each" if keys
              else "no key — nothing can be asked a question")
    )

    out.append(
        Check("TOOLS", "web search", State.OK if env.tavily_api_key else State.OFF,
              "key set" if env.tavily_api_key
              else "not configured — web_search is not offered")
    )
    out.append(
        Check("TOOLS", "mail", State.OK if env.gmail_app_password else State.OFF,
              f"reading {env.gmail_address}" if env.gmail_app_password
              else "not configured — read_mail is not offered")
    )
    key = env.token_encryption_key
    configured = env.google_client_id and env.google_client_secret and key
    out.append(
        Check("TOOLS", "calendar", State.OK if configured else State.OFF,
              "per-user OAuth ready" if configured
              else "not configured — the calendar tools are not offered")
    )
    # Two switches, and off is a decision rather than a gap. A deployment that reads Jira
    # and does not write to it is a whole valid deployment, so writing OFF is not a fault.
    writes = bool(env.jira_client_id and env.jira_client_secret and key and env.jira_write_enabled)
    out.append(
        Check("TOOLS", "jira writes", State.OK if writes else State.OFF,
              ("on, as whoever is asking"
               + (" — including create_project" if env.jira_allow_create_project else ""))
              if writes else "off — the Jira write tools are not offered")
    )

    # The one with a default that is wrong as soon as the app is not on a laptop.
    if env.registration_invite_code is None and not env.allowed_domains:
        out.append(Check("REGISTRATION", "who may sign up", State.BROKEN,
                         "ANYONE who can reach the URL — set REGISTRATION_INVITE_CODE"))
    else:
        how = []
        if env.registration_invite_code is not None:
            how.append("invite code")
        if env.allowed_domains:
            how.append(f"domains: {', '.join(sorted(env.allowed_domains))}")
        out.append(Check("REGISTRATION", "who may sign up", State.OK, " + ".join(how)))

    return out


MARKS = {State.OK: "ok  ", State.BROKEN: "FAIL", State.OFF: "off "}


def render(checks: list[Check]) -> str:
    """The report as text, grouped, in the order the checks were declared."""
    lines: list[str] = []
    for group in dict.fromkeys(c.group for c in checks):
        lines.append(group)
        for check in (c for c in checks if c.group == group):
            lines.append(f"  {MARKS[check.state]}  {check.name:<14} {check.detail}")
        lines.append("")

    broken = sum(1 for c in checks if c.state is State.BROKEN)
    off = sum(1 for c in checks if c.state is State.OFF)
    if broken:
        lines.append(f"{broken} broken, {off} off on purpose.")
    else:
        lines.append(f"Nothing broken. {off} feature(s) off on purpose.")
    return "\n".join(lines)
