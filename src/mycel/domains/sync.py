"""The sync domain: pull one source and push its data up to gold.

    fetch service      call sources/, write the original payload down to bronze
    transform service  run etl/ bronze -> silver -> gold
    check service      run etl/checks/; on failure stop, do not write the layer above

Every step is idempotent — re-running the same window gives the same result, which is what
makes a failed sync safe to simply run again.

Its main caller is `scheduler/` on a timer, not an endpoint: a sync takes as long as the
provider takes, and nothing is waiting on the answer.

**And a timer has nobody signed in**, which is why one person — the syncer, the first to
connect Jira — lends their consent to every background read. One access token is built per
sync and spent across it, so a tick costs one refresh rather than one per issue.

That makes the syncer a single point of failure with a quiet failure mode: they leave, or
revoke the app, and every tick fails while the dashboard merely looks like a quiet week. So
a tick that fails for want of a token logs at `error`, not `warning`, and a tick that
succeeds stamps `last_sync_at` — which is what `core/doctor.py` reads to say the thing out
loud.
"""

import time
from dataclasses import dataclass

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.postgres.session import session_scope
from mycel.infra.vectors.client import configured as vectors_configured
from mycel.observability.metrics import records_written, sync_duration_seconds
from mycel.services.fetch import fetch_jira
from mycel.services.jira_oauth import mark_synced, syncer_token
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
    issue is re-read, and bronze cannot replay a field it was never given. Priority hit
    this in batch 041 and sprint hit it in the same batch, which is twice too often for a
    hand-written one-off script.

    Not on a schedule and not the ordinary path: this reads every issue in the project on
    every call. It is a migration step for the data, run once after a field is added.
    """
    auth, _ = await _syncer_auth()
    async with session_scope() as session:
        fetched = await fetch_jira(session, auth, since=None)

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
    auth, syncer_id = await _syncer_auth()
    async with session_scope() as session:
        fetched = await fetch_jira(session, auth)

    async with session_scope() as session:
        result = await transform(session, keys=fetched.keys)

    indexed = await _index_gold()
    await mark_synced(syncer_id)

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


async def _syncer_auth() -> tuple[Auth, int]:
    """The grant every background read runs on, and whose it is.

    Raises `NotConnected` when nobody holds the role or their consent has lapsed. It is
    raised rather than swallowed so the scheduler's own handler logs it — and that handler
    logs it at `error`, because "nobody has connected Jira" is not a transient failure that
    the next tick fixes.
    """
    token, cloud_id, user_id = await syncer_token()
    return Auth(access_token=token, cloud_id=cloud_id), user_id


async def _index_gold() -> int:
    """Embed what gold has touched, if this deployment has somewhere to put it.

    Runs after the transform and outside its transaction: embedding is CPU work on a local
    model, and holding a Postgres transaction open across it holds it for seconds at a time
    for no reason.

    **A failure here does not fail the sync.** Gold is already written and correct; a search
    index one tick behind is a degraded search, while a sync that reports failure is a
    scheduler retrying work it has already done. That is the argument `notify/` makes for
    never raising out of a side effect.

    Only what moved is embedded — `index_items` compares each row’s `updated_at` against
    what Qdrant holds — so a quiet tick costs one query and no model time.
    """
    if not vectors_configured():
        return 0

    project = get_settings().jira_project_key
    if not project:
        return 0

    try:
        from mycel.infra.vectors import indexer

        async with session_scope() as session:
            result = await indexer.index_project(session, project)
        return result.embedded
    except Exception:
        log.warning("indexing gold failed; search is behind", exc_info=True)
        return 0
