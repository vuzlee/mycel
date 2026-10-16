"""The sync domain: pull one source and push its data up to gold."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError
from mycel.core.logging import get_logger
from mycel.infra.postgres.locks import try_lock
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.session import session_scope
from mycel.observability.metrics import records_written, sync_duration_seconds
from mycel.queue.job import Job, JobKind
from mycel.services import access, enqueue
from mycel.services.fetch import fetch_jira
from mycel.services.transform import transform
from mycel.sources.jira import Auth

log = get_logger(__name__)


@dataclass(frozen=True)
class SyncResult:
    """One run, counted at each layer."""

    fetched: int
    silver_items: int
    silver_worklogs: int
    items: int
    worklogs: int


async def refetch_jira() -> SyncResult:
    """Read the whole project again, ignoring the watermark, then transform it."""
    async with session_scope() as session:
        fetched = await fetch_jira(session, service_auth(), since=None)

    async with session_scope() as session:
        result = await transform(session, keys=fetched.keys)

    log.warning(
        "refetched whole project",
        extra={"fetched": fetched.issues, "items": result.items},
    )
    return SyncResult(
        fetched=fetched.issues,
        silver_items=result.silver_items,
        silver_worklogs=result.silver_worklogs,
        items=result.items,
        worklogs=result.worklogs,
    )


async def sync_jira() -> SyncResult:
    """Fetch, then transform what the fetch brought in."""
    started = time.monotonic()
    try:
        async with session_scope() as session:
            fetched = await fetch_jira(session, service_auth())

        async with session_scope() as session:
            result = await transform(session, keys=fetched.keys)
    except Exception as exc:
        await _record(error=str(exc) or type(exc).__name__)
        raise

    await _queue_index()
    await _record()
    refreshed = await access.refresh_everyone()

    # Observed after the transform, not in a `finally`: a failed sync has no useful duration.
    sync_duration_seconds.labels(domain="jira").observe(time.monotonic() - started)
    for layer, count in (
        ("bronze", fetched.issues),
        ("silver", result.silver_items),
        ("gold", result.items),
    ):
        records_written.labels(domain="jira", layer=layer).set(count)

    log.info(
        "sync finished",
        extra={
            "fetched": fetched.issues,
            "silver_items": result.silver_items,
            "silver_worklogs": result.silver_worklogs,
            "items": result.items,
            "worklogs": result.worklogs,
            "access_refreshed": refreshed,
        },
    )
    return SyncResult(
        fetched=fetched.issues,
        silver_items=result.silver_items,
        silver_worklogs=result.silver_worklogs,
        items=result.items,
        worklogs=result.worklogs,
    )


#: One sync at a time, whether the scheduler or a fresh connection asked for it.
LOCK = "sync:jira"


async def run(job: Job) -> None:
    """A sync asked for out of turn, by a person who just connected Jira."""
    async with try_lock(LOCK) as acquired:
        if not acquired:
            log.info("sync already running, this request is covered", extra={"job_id": job.job_id})
            return
        await sync_jira()


def service_auth() -> Auth:
    """The deployment's own Jira identity: the service account's token and its site."""
    settings = get_settings()
    if settings.jira_service_token is None or not settings.jira_cloud_id:
        raise ConfigError("JIRA_SERVICE_TOKEN and JIRA_CLOUD_ID must be set for the sync to run")
    return Auth(settings.jira_service_token.get_secret_value(), settings.jira_cloud_id)


async def _record(error: str | None = None) -> None:
    """Stamp this run in `app.sync_state`. Best-effort: a stamp must not fail a sync."""
    try:
        async with session_scope() as session:
            await AccountRepository(session).record_sync(datetime.now(UTC), error)
    except Exception:
        log.warning("could not record the sync run", exc_info=True)


async def _queue_index() -> None:
    """Hand the embedding to the ingest worker; the scheduler never loads a model."""
    job = Job(kind=JobKind.INDEX_GOLD)
    async with session_scope() as session:
        await enqueue.stage(session, job)
    await enqueue.send(job)
