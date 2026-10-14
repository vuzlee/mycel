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
from mycel.infra.redis.client import get_client
from mycel.observability.metrics import (
    dead_letters,
    queue_consumers,
    queue_ready,
    redis_memory_ratio,
)
from mycel.queue.replay import depths, work_queues
from mycel.services.auth import sweep_expired_sessions
from mycel.services.enqueue import relay

WATCHDOG_INTERVAL_SECONDS = 60
RELAY_INTERVAL_SECONDS = 5

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


async def _count_queues() -> None:
    for queue, waiting in (await depths()).items():
        dead_letters.labels(queue=queue).set(waiting)
        if waiting:
            log.warning("jobs parked in %s", queue, extra={"count": waiting})
    for queue, (ready, consumers) in (await work_queues()).items():
        queue_ready.labels(queue=queue).set(ready)
        queue_consumers.labels(queue=queue).set(consumers)
    info = await (await get_client()).info("memory")
    if limit := int(info.get("maxmemory", 0)):
        redis_memory_ratio.set(int(info.get("used_memory", 0)) / limit)


async def run_forever() -> None:
    """Run each timer until stopped; an advisory lock per timer keeps replicas from doubling."""
    settings = get_settings()
    timers: list[tuple[str, Callable[[], Awaitable[None]], int]] = [
        ("sync:jira", _sync, settings.sync_interval_seconds),
        ("sweep:sessions", _sweep, settings.session_sweep_interval_seconds),
        ("watchdog:documents", watchdog, WATCHDOG_INTERVAL_SECONDS),
        ("relay:outbox", relay, RELAY_INTERVAL_SECONDS),
        ("count:queues", _count_queues, WATCHDOG_INTERVAL_SECONDS),
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
