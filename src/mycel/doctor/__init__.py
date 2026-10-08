"""What is configured, what is broken, and what is off on purpose."""

import asyncio

from mycel.core.config import Settings
from mycel.doctor.declared import declared
from mycel.doctor.probes import (
    REMOTE_TIMEOUT_SECONDS,
    _gateway,
    _jira,
    _langfuse,
    _minio,
    _parser,
    _postgres,
    _probe,
    _qdrant,
    _rabbitmq,
    _redis,
    _service_token_expiry,
    _upstreams,
)
from mycel.doctor.report import Check, State, render
from mycel.infra.objects import client as object_store
from mycel.infra.vectors import client as vector_store

__all__ = ["Check", "State", "declared", "render", "run"]


async def run(settings: Settings | None = None) -> list[Check]:
    """Every check, concurrently. Returns the report rather than printing it."""
    env = settings or Settings()

    jobs = [
        _probe("litellm", "MODELS", lambda: _gateway(env), missing=None),
        _probe("upstreams", "MODELS", lambda: _upstreams(env), missing=None),
        _probe("postgres", "STORES", lambda: _postgres(env), missing=None),
        _probe("rabbitmq", "STORES", lambda: _rabbitmq(env), missing=None),
        _probe("redis", "STORES", lambda: _redis(env), missing=None),
        _probe(
            "jira",
            "SOURCES",
            lambda: _jira(env),
            missing=None
            if (env.jira_service_token and env.jira_cloud_id)
            else "no service account — set JIRA_SERVICE_TOKEN and JIRA_CLOUD_ID",
            timeout=REMOTE_TIMEOUT_SECONDS,
        ),
        _probe(
            "qdrant",
            "SEARCH",
            lambda: _qdrant(env),
            missing=None
            if vector_store.configured(env)
            else "not configured — rag_search is not offered to the model",
        ),
        _probe(
            "minio",
            "DOCUMENTS",
            lambda: _minio(env),
            missing=None
            if object_store.configured(env)
            else "not configured — documents cannot be uploaded",
        ),
        _probe("ingest", "DOCUMENTS", lambda: _parser(env), missing=None),
        _probe(
            "langfuse",
            "OBSERVABILITY",
            lambda: _langfuse(env),
            missing=None
            if (env.langfuse_public_key and env.langfuse_secret_key)
            else "not configured — the app runs, nothing records what it did",
        ),
    ]
    checks = list(await asyncio.gather(*jobs))

    # Not probes: nothing to connect to, but the answer is what somebody wants to know.
    checks.extend(declared(env))
    expiry = _service_token_expiry(env)
    if expiry is not None:
        checks.append(expiry)
    return checks
