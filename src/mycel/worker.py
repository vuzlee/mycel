"""The worker process: which domain runs each kind of job.

python -m mycel.worker [--queue ingest]
"""

import httpx
import redis.exceptions
import sqlalchemy.exc

from mycel.agents.core.exceptions import AgentError
from mycel.domains import chat, index, ingest
from mycel.llm.budget import BudgetExceeded
from mycel.queue import consumer
from mycel.queue.handler import Handler
from mycel.queue.job import INGEST_KINDS, Job, JobKind

#: Never retried: another attempt spends money the job does not have.
FINAL: tuple[type[Exception], ...] = (BudgetExceeded,)

#: Retried after a delay: a provider 503, a rate limit, a dropped socket or store.
TRANSIENT: tuple[type[Exception], ...] = (
    AgentError,
    OSError,
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
    sqlalchemy.exc.OperationalError,
    sqlalchemy.exc.InterfaceError,
    httpx.TransportError,
)


async def run(job: Job) -> None:
    if job.kind is JobKind.INGEST:
        await ingest.run(job)
    elif job.kind is JobKind.DELETE_DOCUMENT:
        await ingest.delete(job)
    elif job.kind is JobKind.INDEX_GOLD:
        await index.run(job)
    else:
        await chat.run(job)


async def record_failure(job: Job, error: str) -> None:
    if job.kind in INGEST_KINDS:
        await ingest.record_failure(job, error)
    else:
        await chat.record_failure(job, error)


HANDLER = Handler(run=run, record_failure=record_failure, final=FINAL, transient=TRANSIENT)

if __name__ == "__main__":
    raise SystemExit(consumer.main(HANDLER))
