"""Connections the doctor tries, each with a timeout."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from mycel.core.config import Settings
from mycel.doctor.report import Check, State

#: Long enough for a local container, short enough that a wrong host does not look like a hang.
TIMEOUT_SECONDS = 3.0

#: For anything across the internet.
REMOTE_TIMEOUT_SECONDS = 15.0

#: One HTTP call to the gateway or a self-hosted model, on this machine or the LAN.
GATEWAY_TIMEOUT_SECONDS = 5.0


async def _probe(
    name: str,
    group: str,
    probe: Callable[[], Awaitable[str]],
    *,
    missing: str | None,
    timeout: float = TIMEOUT_SECONDS,
) -> Check:
    """Run one probe, or report why it was not run."""
    if missing is not None:
        return Check(group, name, State.OFF, missing)
    try:
        detail = await asyncio.wait_for(probe(), timeout=timeout)
        return Check(group, name, State.OK, detail)
    except TimeoutError:
        return Check(group, name, State.BROKEN, f"no answer in {timeout:.0f}s")
    except Exception as exc:
        # The class name too: an empty OSError message says nothing.
        message = str(exc).strip() or type(exc).__name__
        return Check(group, name, State.BROKEN, message.splitlines()[0][:90])


async def _postgres(settings: Settings) -> str:
    from sqlalchemy import text

    from mycel.infra.postgres.session import session_scope

    async with session_scope() as session:
        count = await session.scalar(
            text(
                "select count(*) from information_schema.tables "
                "where table_schema in ('bronze','silver','gold','app')"
            )
        )
        # Whether this role could drop the schema it reads.
        owner = await session.scalar(
            text(
                "select count(*) from pg_tables where schemaname = 'gold' "
                "and tableowner = current_user"
            )
        )
        user = await session.scalar(text("select current_user"))
    role = (
        f"as {user}, which owns the schema — set MYCEL_APP_PASSWORD and connect as mycel_app"
        if owner
        else f"as {user}, rows only — no DDL"
    )
    return f"connected {role}; {count} tables"


async def _rabbitmq(settings: Settings) -> str:
    import aio_pika

    connection = await aio_pika.connect_robust(settings.rabbitmq_url, timeout=TIMEOUT_SECONDS)
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
    # noeviction matters: an evicted budget reads back as a full ceiling.
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


async def _gateway(settings: Settings) -> str:
    """The gateway answers and serves every host model. Free: no model is called."""
    names = sorted({m["id"] for m in (await _ask_gateway(settings, "/v1/models"))["data"]})
    if not names:
        raise RuntimeError("the gateway answers but serves no model")
    missing = [m.name for m in settings.host_models if m.name not in names]
    if missing:
        raise RuntimeError(
            f"host_models names {', '.join(missing)}, which the gateway does not serve "
            f"(it serves {', '.join(names)})"
        )
    return f"{len(names)} models: {', '.join(names)}"


async def _upstreams(settings: Settings) -> str:
    """Whether each self-hosted upstream behind the gateway answers at all."""
    import httpx2

    bases: dict[str, str] = {}
    for entry in (await _ask_gateway(settings, "/model/info"))["data"]:
        base = entry.get("litellm_params", {}).get("api_base")
        if base:
            bases.setdefault(base, entry["model_name"])
    if not bases:
        return "no self-hosted upstream"

    down: list[str] = []
    async with httpx2.AsyncClient(timeout=GATEWAY_TIMEOUT_SECONDS) as client:
        for base, model in sorted(bases.items(), key=lambda kv: kv[1]):
            # Any HTTP answer, 401 included, means the host is up.
            try:
                await client.get(f"{base.rstrip('/')}/models")
            except Exception:  # no answer at all is the one failure
                down.append(model)
    if down:
        raise RuntimeError(f"not answering: {', '.join(down)} — calls fall back")
    return f"{len(bases)} answering: {', '.join(sorted(bases.values()))}"


async def _ask_gateway(settings: Settings, path: str) -> dict[str, Any]:
    import httpx2

    key = settings.litellm_api_key.get_secret_value() if settings.litellm_api_key else ""
    async with httpx2.AsyncClient(timeout=GATEWAY_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{settings.litellm_base_url.rstrip('/')}{path}",
            headers={"authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
    found: dict[str, Any] = response.json()
    return found


async def _langfuse(settings: Settings) -> str:
    return f"keys set, sending to {settings.langfuse_base_url}"
