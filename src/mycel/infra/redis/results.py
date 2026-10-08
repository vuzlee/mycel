"""A finished job's answer, held with a TTL until polled; Postgres holds the record."""

from typing import Literal

from pydantic import BaseModel

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client

log = get_logger(__name__)


class JobResult(BaseModel):
    """What a caller gets back when polling for a job; `answer` is markdown."""

    job_id: str
    status: Literal["running", "done", "failed"]
    answer: str | None = None
    spent_usd: str | None = None
    error: str | None = None


def _key(job_id: str) -> str:
    return _kv.key("result", job_id)


async def mark_running(job_id: str) -> None:
    """Record that a worker has picked this job up."""
    await _write(JobResult(job_id=job_id, status="running"))


async def store(job_id: str, answer: str, spent_usd: str) -> None:
    await _write(JobResult(job_id=job_id, status="done", answer=answer, spent_usd=spent_usd))


async def store_failure(job_id: str, error: str) -> None:
    """Record that a job is out of retries and is not coming back."""
    await _write(JobResult(job_id=job_id, status="failed", error=error[:500]))


async def fetch(job_id: str) -> JobResult | None:
    """A job's state, or `None` if unknown or expired."""
    found = await _kv.get(await get_client(), _key(job_id))
    return None if found is None else JobResult.model_validate(found)


async def _write(result: JobResult) -> None:
    """Single write path, refreshing the TTL on every state."""
    await _kv.put(
        await get_client(),
        _key(result.job_id),
        result.model_dump_json(),
        get_settings().result_ttl_seconds,
    )
