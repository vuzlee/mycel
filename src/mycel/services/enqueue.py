"""Push one job onto the queue and return its job_id.

Wraps `queue/` into a single call: the domain need not know what the queue runs on.
Every job carries an idempotency key, so calling twice does not produce two duplicate
reports.

The key is derived from the work in `queue/job.py` rather than passed in here, so two
callers asking the same question cannot accidentally defeat it by each generating their
own.
"""

from mycel.queue.job import Job, JobKind
from mycel.queue.producer import publish


async def enqueue_report(question: str, conversation_id: int, history: str = "") -> str:
    """Queue a report and return the job id to poll with.

    `history` is the earlier turns of this thread, already trimmed by the domain. It rides
    in the payload rather than being read by the worker on purpose: the idempotency key
    hashes the payload, so the same question asked twice at different points in a thread
    must differ here or the second job is dropped as a duplicate of the first.
    """
    job = Job(
        kind=JobKind.REPORT,
        payload={
            "question": question,
            "conversation_id": conversation_id,
            "history": history,
        },
    )
    return await publish(job)


async def enqueue_summary(project: str, days: int, conversation_id: int) -> str:
    """Queue a progress summary and return the job id to poll with.

    `conversation_id` is in the payload rather than derived by the worker: the thread
    exists before the job does, so a run that dies still has somewhere to be recorded.
    """
    job = Job(
        kind=JobKind.SUMMARY,
        payload={"project": project, "days": days, "conversation_id": conversation_id},
    )
    return await publish(job)
