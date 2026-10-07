"""The sync domain: pull one source and push its data up to gold.

    fetch service      call sources/, write the original payload down to bronze
    transform service  run etl/ bronze -> silver -> gold
    check service      run etl/checks/; on failure stop, do not write the layer above

Every step is idempotent — re-running the same window gives the same result, which is what
makes a failed sync safe to simply run again.

Its main caller is `scheduler/` on a timer, not an endpoint: a sync takes as long as the
provider takes, and nothing is waiting on the answer.

**A timer has nobody signed in, so it reads as the deployment.** The service account in
`JIRA_SERVICE_TOKEN` reads every project it may browse; no person's token is used, so
nobody leaving can stop it. Each run is recorded in `app.sync_state`, success or failure,
which is what `doctor.py` reads — a stopped sync and a quiet week look the same on a
dashboard.

After the data, access: every connected person's projects are asked of Jira again, so
someone removed from a project there loses it here within one tick.
"""

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
    #: How many gold rows were embedded this pass. Zero when nothing moved, and also zero
    #: when QDRANT_URL is unset — the two are told apart in the log, not here.
    indexed: int = 0


async def refetch_jira() -> SyncResult:
    """Read the whole project again, ignoring the watermark, then transform it.

    Needed whenever a FIELD is added rather than a row: the watermark is the newest
    `fetched_at` in bronze, so adding to the fields a sync asks for moves nothing — no
    issue is re-read, and bronze cannot replay a field it was never given. Priority and
    sprint both hit this, which is twice too often for a hand-written one-off script.

    Not on a schedule and not the ordinary path: this reads every issue in the project on
    every call. It is a migration step for the data, run once after a field is added.
    """
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
    """Fetch, then transform what the fetch brought in.

    Two transactions rather than one. Jira keeps its history, so a failed fetch can
    simply be re-run; the split is there because a failed transform must leave bronze intact, or the
    replay it exists for has nothing to replay.
    """
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

    # Observed after the transform, not in a `finally`: a sync that failed has no duration
    # worth plotting, and a row count from a half-run would read as data loss.
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
    """The deployment's own Jira identity: the service account's token and its site.

    Raises `ConfigError` when either is missing. The scheduler logs it at `error`: with no
    identity there is no sync, and the dashboard would only look quiet.
    """
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
    """Embed what gold has touched, if this deployment has somewhere to put it.

    Runs after the transform and outside its transaction: embedding is CPU work on a local
    model, and holding a Postgres transaction open across it holds it for seconds at a time
    for no reason.

    **A failure here does not fail the sync.** Gold is already written and correct; a search
    index one tick behind is a degraded search, while a sync that reports failure is a
    scheduler retrying work it has already done.

    Only what moved is embedded — `index_items` compares each row’s `updated_at` against
    what Qdrant holds — so a quiet tick costs one query and no model time.
    """
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
