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

#: Advisory lock shared by every replica, so only one syncs at a time.
SYNC_LOCK = "sync:jira"

#: Separate lock so the sweep and the sync never wait on each other.
SWEEP_LOCK = "sweep:sessions"

WATCHDOG_LOCK = "watchdog:documents"
WATCHDOG_INTERVAL_SECONDS = 60

log = get_logger(__name__)


async def run_sync_once() -> None:
    """One sync tick; skips if another process is syncing."""
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
    """Run the sync, sweep and watchdog timers until stopped."""
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
