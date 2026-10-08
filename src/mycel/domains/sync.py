"""The sync domain: pull one source and push its data up to gold."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.repositories.gold import GoldRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.vectors.client import configured as vectors_configured
from mycel.observability.metrics import records_written, sync_duration_seconds
from mycel.services import access
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
    #: How many gold rows were embedded this pass.
    indexed: int = 0


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

    indexed = await _index_gold()
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
            "indexed": indexed,
            "access_refreshed": refreshed,
        },
    )
    return SyncResult(
        fetched=fetched.issues,
        silver_items=result.silver_items,
        silver_worklogs=result.silver_worklogs,
        items=result.items,
        worklogs=result.worklogs,
        indexed=indexed,
    )


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


async def _index_gold() -> int:
    """Embed what gold has touched, if this deployment has somewhere to put it."""
    if not vectors_configured():
        return 0

    try:
        from mycel.infra.vectors import indexer

        embedded = 0
        async with session_scope() as session:
            for project in await GoldRepository(session).projects():
                embedded += (await indexer.index_project(session, project)).embedded
        return embedded
    except Exception:
        log.warning("indexing gold failed; search is behind", exc_info=True)
        return 0
