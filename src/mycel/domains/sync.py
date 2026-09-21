"""The sync domain: pull one source and push its data up to gold.

    fetch service      call sources/, write the original payload down to bronze
    transform service  run etl/ bronze -> silver -> gold
    check service      run etl/checks/; on failure stop, do not write the layer above

Every step is idempotent — re-running the same window gives the same result, which is what
makes a failed sync safe to simply run again.

Its main caller is `scheduler/` on a timer, not an endpoint: a sync takes as long as the
provider takes, and nothing is waiting on the answer.
"""

from dataclasses import dataclass

from mycel.core.logging import get_logger
from mycel.infra.postgres.session import session_scope
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


async def sync_jira() -> SyncResult:
    """Fetch, then transform what the fetch brought in.

    Two transactions rather than one. With Telegram this was forced — an acknowledged
    update is dropped by the provider, so a rollback lost it permanently. Jira keeps its
    history and a failed fetch can simply be re-run, so the constraint no longer binds;
    the split stays because the reason it is *good* never depended on that. A failed
    transform must leave bronze intact, or the replay it exists for has nothing to replay.
    """
    async with session_scope() as session:
        fetched = await fetch_jira(session)

    async with session_scope() as session:
        result = await transform(session, keys=fetched.keys)

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
