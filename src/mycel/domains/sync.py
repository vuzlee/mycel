"""The sync domain: run one plugin's background pull, never twice at once."""

from mycel.core.logging import get_logger
from mycel.infra.postgres.locks import try_lock
from mycel.plugins import registry
from mycel.plugins.base import Plugin
from mycel.queue.job import Job

log = get_logger(__name__)


def lock(plugin: Plugin) -> str:
    """One sync per plugin at a time, whether the timer or a fresh connection asked."""
    return f"sync:{plugin.key}"


async def run(job: Job) -> None:
    """A sync asked for out of turn, by a person who just connected."""
    plugin = registry.get(str(job.payload.get("plugin", "")))
    if plugin is None or not plugin.syncs:
        log.warning("sync job names no syncing plugin", extra={"payload": job.payload})
        return
    async with try_lock(lock(plugin)) as acquired:
        if not acquired:
            log.info("sync already running, this request is covered", extra={"job_id": job.job_id})
            return
        await plugin.sync()
