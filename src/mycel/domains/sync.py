"""The sync domain: pull one source and push its data up to gold.

    fetch service      call sources/, write the original payload down to bronze
    transform service  run etl/ bronze -> silver -> gold
    check service      run etl/checks/; on failure stop, do not write the layer above

Every step is idempotent — re-running the same window gives the same result, which is what
makes a failed sync safe to simply run again.

Its main caller is `scheduler/` on a timer, not an endpoint: a sync takes as long as the
provider takes, and nothing is waiting on the answer.
"""

import time
from dataclasses import dataclass

from mycel.core.logging import get_logger
from mycel.infra.postgres.session import session_scope
from mycel.observability.metrics import records_written, sync_duration_seconds
from mycel.services.fetch import fetch_jira
from mycel.services.transform import transform

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
    """Read the whole project again, ignoring the watermark, then transform it.

    Needed whenever a FIELD is added rather than a row: the watermark is the newest
    `fetched_at` in bronze, so adding to the fields a sync asks for moves nothing — no
    issue is re-read, and bronze cannot replay a field it was never given. Priority hit
    this in batch 041 and sprint hit it in the same batch, which is twice too often for a
    hand-written one-off script.

    Not on a schedule and not the ordinary path: this reads every issue in the project on
    every call. It is a migration step for the data, run once after a field is added.
    """
    async with session_scope() as session:
        fetched = await fetch_jira(session, since=None)

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

    Two transactions rather than one. With Telegram this was forced — an acknowledged
    update is dropped by the provider, so a rollback lost it permanently. Jira keeps its
    history and a failed fetch can simply be re-run, so the constraint no longer binds;
    the split stays because the reason it is *good* never depended on that. A failed
    transform must leave bronze intact, or the replay it exists for has nothing to replay.
    """
    started = time.monotonic()
    async with session_scope() as session:
        fetched = await fetch_jira(session)

    async with session_scope() as session:
        result = await transform(session, keys=fetched.keys)

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
        },
    )
    return SyncResult(
        fetched=fetched.issues,
        silver_items=result.silver_items,
        silver_worklogs=result.silver_worklogs,
        items=result.items,
        worklogs=result.worklogs,
    )
