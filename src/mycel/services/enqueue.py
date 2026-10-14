"""Queue jobs through the outbox: written with the row, published after the commit."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.outbox import OutboxRepository
from mycel.infra.postgres.session import session_scope
from mycel.queue import context
from mycel.queue.job import Job, JobKind
from mycel.queue.producer import publish

log = get_logger(__name__)

#: The request publishes at once; the relay only takes rows older than this.
RELAY_AFTER = timedelta(seconds=10)
RELAY_BATCH = 100
KEEP_PUBLISHED = timedelta(days=1)


async def stage(session: AsyncSession, job: Job) -> Job:
    """Write the job in the caller's transaction. Publish it with `send` once that commits."""
    await OutboxRepository(session).add(job.job_id, job.model_dump(mode="json"), context.inject())
    return job


async def send(job: Job) -> None:
    """Publish a committed job now. A failure is left to the relay, never raised."""
    try:
        await publish(job)
    except Exception:
        log.warning("publish failed, the relay will retry", extra={"job_id": job.job_id})
        return
    await _mark(job.job_id)


async def relay() -> None:
    """Publish what a request committed but could not send, then drop old sent rows."""
    for _ in range(RELAY_BATCH):
        if not await _relay_one():
            break
    async with session_scope() as session:
        await OutboxRepository(session).prune(KEEP_PUBLISHED)


async def _relay_one() -> bool:
    """One row, published and marked in its own transaction: a later failure cannot unmark it."""
    async with session_scope() as session:
        repo = OutboxRepository(session)
        found = await repo.unpublished(RELAY_AFTER, 1)
        if not found:
            return False
        body, headers = found[0]
        try:
            job = Job.model_validate(body)
        except ValueError:
            # A kind this build no longer knows would block the queue head forever.
            log.error("outbox row unreadable, skipped", extra={"job_id": body.get("job_id")})
            await repo.mark_published(str(body.get("job_id")))
            return True
        await publish(job, headers)
        await repo.mark_published(job.job_id)
    log.info("outbox relayed", extra={"job_id": job.job_id})
    return True


async def _mark(job_id: str) -> None:
    async with session_scope() as session:
        await OutboxRepository(session).mark_published(job_id)


def chat_job(
    question: str,
    conversation_id: int,
    history: str,
    user_id: int,
    chips: list[str] | None,
    previous: str,
    context: str,
) -> Job:
    """History rides in the payload, read once here."""
    return Job(
        kind=JobKind.CHAT,
        payload={
            "question": question,
            "conversation_id": conversation_id,
            "history": history,
            "user_id": user_id,
            "chips": sorted(chips) if chips is not None else None,
            "previous": previous,
            "context": context,
        },
    )


def ingest_job(document_id: int) -> Job:
    return Job(kind=JobKind.INGEST, payload={"document_id": document_id})


def delete_job(document_id: int) -> Job:
    return Job(kind=JobKind.DELETE_DOCUMENT, payload={"document_id": document_id})
