"""The loop: run a domain on a timer, forever, without ever running it twice at once."""

import asyncio
from collections.abc import Awaitable, Callable

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError
from mycel.core.logging import get_logger
from mycel.domains.ingest import watchdog
from mycel.domains.sync import sync_jira
from mycel.infra.postgres.locks import try_lock
from mycel.infra.postgres.session import session_scope
from mycel.services.auth import sweep_expired_sessions

#: The advisory lock name. Every process running this scheduler contends for the same one,
#: which is the point: two replicas are for availability, not for twice the syncing.
SYNC_LOCK = "sync:jira"

#: A second lock, so the sweep does not wait behind a long sync and vice versa. They share
#: nothing and contend for nothing.
SWEEP_LOCK = "sweep:sessions"

WATCHDOG_LOCK = "watchdog:documents"
WATCHDOG_INTERVAL_SECONDS = 60

log = get_logger(__name__)


async def run_sync_once() -> None:
    """One tick. Skips rather than waits if another process is mid-sync.

    **A missing service account is logged at `error`, not `warning`.** Every other failure
    here is the next tick's work — a provider was slow, a connection dropped — and the data
    catches up. This one does not: every later tick fails the same way, and from the
    dashboard a stale project is indistinguishable from a quiet week.
    """
    async with try_lock(SYNC_LOCK) as acquired:
        if not acquired:
            log.info("sync already running elsewhere, skipping this tick")
            return
        try:
            await sync_jira()
        except ConfigError as exc:
            log.error("sync cannot run: %s", exc)


async def run_sweep_once() -> None:
    """Delete sessions that have already expired. Skips if another process is sweeping."""
    async with try_lock(SWEEP_LOCK) as acquired:
        if not acquired:
            log.info("session sweep already running elsewhere, skipping this tick")
            return
        async with session_scope() as session:
            deleted = await sweep_expired_sessions(session)
        if deleted:
            log.info("expired sessions swept", extra={"deleted": deleted})


async def run_watchdog_once() -> None:
    """Fail documents stuck processing; resend deletes that never finished."""
    async with try_lock(WATCHDOG_LOCK) as acquired:
        if acquired:
            await watchdog()


async def run_forever() -> None:
    """Tick both loops until the process is stopped.

    A failed tick is logged and the loop continues. Stopping the scheduler because one
    sync failed is how a transient provider outage turns into a permanent one. Nothing is
    lost by a late tick — Jira keeps its own history — so a tick that fails is simply the
    next tick's work.

    The sweep runs on its own timer because it has nothing to do with freshness: syncing
    every fifteen minutes and sweeping once a day are two different questions.
    """
    settings = get_settings()
    log.info(
        "scheduler started",
        extra={
            "interval_seconds": settings.sync_interval_seconds,
            "sweep_interval_seconds": settings.session_sweep_interval_seconds,
        },
    )
    await asyncio.gather(
        _loop("sync", run_sync_once, settings.sync_interval_seconds),
        _loop("session sweep", run_sweep_once, settings.session_sweep_interval_seconds),
        _loop("document watchdog", run_watchdog_once, WATCHDOG_INTERVAL_SECONDS),
    )


async def _loop(name: str, tick: Callable[[], Awaitable[None]], interval: int) -> None:
    """One timer. A failing tick is the next tick's work, never the loop's end."""
    while True:
        try:
            await tick()
        except Exception:
            log.exception("%s tick failed", name)
        await asyncio.sleep(interval)
