"""The worker process: which domain runs each kind of job.

python -m mycel.worker [--queue ingest]
"""

from types import ModuleType

import botocore.exceptions
import httpx2
import redis.exceptions
import sqlalchemy.exc
from qdrant_client.http.exceptions import ResponseHandlingException

from mycel.agents.core.exceptions import (
    DegenerateLoop,
    OutputValidationFailed,
    RunawayStopped,
    ToolFailed,
    TransportError,
)
from mycel.domains import chat, index, ingest
from mycel.llm.budget import BudgetExceeded
from mycel.queue import consumer
from mycel.queue.handler import Handler
from mycel.queue.job import INGEST_KINDS, Job, JobKind


class UnknownJob(Exception):
    """A kind this worker has no handler for: a newer producer, or a missing entry."""


#: Never retried: another attempt spends money the job does not have, or cannot run at all.
FINAL: tuple[type[Exception], ...] = (
    BudgetExceeded,
    UnknownJob,
    RunawayStopped,
    DegenerateLoop,
    OutputValidationFailed,
    ToolFailed,
)

#: Retried after a delay: a provider 503, a rate limit, a dropped socket or store.
#: Qdrant and S3 wrap their socket errors in their own types, so each is named here.
TRANSIENT: tuple[type[Exception], ...] = (
    TransportError,
    OSError,
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
    sqlalchemy.exc.OperationalError,
    sqlalchemy.exc.InterfaceError,
    sqlalchemy.exc.TimeoutError,
    httpx2.TransportError,
    ResponseHandlingException,
    botocore.exceptions.ConnectionError,
    botocore.exceptions.HTTPClientError,
)


#: Each kind and the domain function that runs it, looked up per job. A kind missing here
#: is parked, never run as chat.
RUNS: dict[JobKind, tuple[ModuleType, str]] = {
    JobKind.CHAT: (chat, "run"),
    JobKind.INGEST: (ingest, "run"),
    JobKind.DELETE_DOCUMENT: (ingest, "delete"),
    JobKind.INDEX_GOLD: (index, "run"),
}


async def run(job: Job) -> None:
    if job.kind not in RUNS:
        raise UnknownJob(f"no handler for job kind {job.kind!r}")
    module, name = RUNS[job.kind]
    await getattr(module, name)(job)


async def record_failure(job: Job, error: str) -> None:
    if job.kind is JobKind.CHAT:
        await chat.record_failure(job, error)
    elif job.kind in INGEST_KINDS:
        await ingest.record_failure(job, error)


HANDLER = Handler(run=run, record_failure=record_failure, final=FINAL, transient=TRANSIENT)

if __name__ == "__main__":
    raise SystemExit(consumer.main(HANDLER))
