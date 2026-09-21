"""The loop: run a domain on a timer, forever, without ever running it twice at once."""

import asyncio

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.domains.sync import sync_jira
from mycel.infra.postgres.locks import try_lock

#: The advisory lock name. Every process running this scheduler contends for the same one,
#: which is the point: two replicas are for availability, not for twice the syncing.
SYNC_LOCK = "sync:jira"

log = get_logger(__name__)


async def run_sync_once() -> None:
    """One tick. Skips rather than waits if another process is mid-sync."""
    async with try_lock(SYNC_LOCK) as acquired:
        if not acquired:
            log.info("sync already running elsewhere, skipping this tick")
            return
        await sync_jira()


async def run_forever() -> None:
    """Tick until the process is stopped.

    A failed tick is logged and the loop continues. Stopping the scheduler because one
    sync failed is how a transient provider outage turns into a permanent one. Nothing is
    lost by a late tick — Jira keeps its own history — so a tick that fails is simply the
    next tick's work.
    """
    interval = get_settings().sync_interval_seconds
    log.info("scheduler started", extra={"interval_seconds": interval})

    while True:
        try:
            await run_sync_once()
        except Exception:
            log.exception("sync tick failed")
        await asyncio.sleep(interval)
