"""Embed gold into Qdrant. Runs on the ingest worker, queued by each sync."""

from datetime import UTC, datetime

from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.gold import GoldRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.vectors.client import configured
from mycel.queue.job import Job

log = get_logger(__name__)


async def run(job: Job) -> None:
    """Every project's items; the indexer skips what has not moved since its last pass."""
    if not configured():
        return
    from mycel.infra.vectors import indexer

    embedded = 0
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    async with session_scope() as session:
        projects = await GoldRepository(session).projects()
    for project in projects:
        # Read, close, then embed: no transaction stays open while the model runs.
        async with session_scope() as session:
            items = await GoldRepository(session).items_between(project, since=epoch)
        embedded += (await indexer.index_items(items)).embedded
    log.info("gold indexed", extra={"embedded": embedded})
