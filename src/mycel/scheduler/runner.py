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

WATCHDOG_INTERVAL_SECONDS = 60

log = get_logger(__name__)


async def _sync() -> None:
    try:
        await sync_jira()
    except ConfigError as exc:
        log.error("sync cannot run: %s", exc)


async def _sweep() -> None:
    async with session_scope() as session:
        deleted = await sweep_expired_sessions(session)
    if deleted:
        log.info("expired sessions swept", extra={"deleted": deleted})


async def run_forever() -> None:
    """Run each timer until stopped; an advisory lock per timer keeps replicas from doubling."""
    settings = get_settings()
    timers: list[tuple[str, Callable[[], Awaitable[None]], int]] = [
        ("sync:jira", _sync, settings.sync_interval_seconds),
        ("sweep:sessions", _sweep, settings.session_sweep_interval_seconds),
        ("watchdog:documents", watchdog, WATCHDOG_INTERVAL_SECONDS),
    ]
    log.info("scheduler started", extra={"timers": {name: every for name, _, every in timers}})
    await asyncio.gather(*(_loop(name, tick, every) for name, tick, every in timers))


async def _locked(name: str, tick: Callable[[], Awaitable[None]]) -> None:
    async with try_lock(name) as acquired:
        if acquired:
            await tick()
        else:
            log.info("%s already running elsewhere, skipping this tick", name)


async def _loop(name: str, tick: Callable[[], Awaitable[None]], interval: int) -> None:
    """One timer. A failing tick is the next tick's work, never the loop's end."""
    while True:
        try:
            await _locked(name, tick)
        except Exception:
            log.exception("%s tick failed", name)
        await asyncio.sleep(interval)
