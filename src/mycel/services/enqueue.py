"""Push one job onto the queue and return its job_id.

Wraps `queue/` into a single call: the domain need not know what the queue runs on.
Every job carries an idempotency key, so calling twice does not produce two duplicate
answers.

The key is derived from the work in `queue/job.py` rather than passed in here, so two
callers asking the same question cannot accidentally defeat it by each generating their
own.
"""

from mycel.queue.job import Job, JobKind
from mycel.queue.producer import publish


async def enqueue_chat(
    question: str, conversation_id: int, history: str = "", user_id: int | None = None
) -> str:
    """Queue a question and return the job id to poll with.

    `history` is the earlier turns of this thread, already trimmed by the domain. It rides
    in the payload rather than being read by the worker on purpose: the idempotency key
    hashes the payload, so the same question asked twice at different points in a thread
    must differ here or the second job is dropped as a duplicate of the first.

    `conversation_id` is in the payload rather than derived by the worker: the thread
    exists before the job does, so a run that dies still has somewhere to be recorded.

    `user_id` rides along so the worker can rebuild who asked. It is in the payload, so it
    is in the idempotency key — which means two people asking the same words no longer
    share a job. That is the point: they are granted different projects, and one shared
    answer is a leak. It also costs a cache hit that used to be free.
    """
    job = Job(
        kind=JobKind.CHAT,
        payload={
            "question": question,
            "conversation_id": conversation_id,
            "history": history,
            "user_id": user_id,
        },
    )
    return await publish(job)
