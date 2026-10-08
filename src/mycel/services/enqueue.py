"""Queue jobs. Callers need not know the queue runs on RabbitMQ."""

from mycel.queue.job import Job, JobKind
from mycel.queue.producer import publish


async def enqueue_chat(
    question: str,
    conversation_id: int,
    history: str,
    user_id: int,
    chips: list[str] | None,
    previous: str,
    context: str,
) -> str:
    """Queue a question; returns the job id. History rides in the payload, read once here."""
    job = Job(
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
    return await publish(job)


def ingest_job(document_id: int) -> Job:
    return Job(kind=JobKind.INGEST, payload={"document_id": document_id})


def delete_job(document_id: int) -> Job:
    return Job(kind=JobKind.DELETE_DOCUMENT, payload={"document_id": document_id})
