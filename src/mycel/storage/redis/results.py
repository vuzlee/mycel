"""Where a finished job's report waits until somebody asks for it.

**This is a holding area, not storage.** Batch 004 moved the work into a second process,
which immediately raises a question that process boundary does not answer: the worker has
the `Report` and the caller has only a job id. Redis with a TTL closes that gap without
deciding anything about the data layer, which is a later branch — `storage/` is still
stubs, and designing the reports table here would mean designing it twice.

What that buys, and what it costs:

  + no migration, no schema, nothing to undo when the real store arrives
  + already in `docker-compose.yml`, and batch 005 wants Redis anyway
  - a report vanishes after `result_ttl_seconds`
  - a Redis restart loses every result, which is why nothing here is treated as a record
    of what was produced

The state lives with the result rather than beside it: one key holds either `running`,
`done` with a report, or `failed` with a reason, so a caller polling gets a straight answer
instead of having to distinguish "no key yet" from "key expired".
"""

import json
from typing import Any, Literal

import redis.asyncio as redis
from pydantic import BaseModel

from mycel.core.config import get_settings
from mycel.core.logging import get_logger

log = get_logger(__name__)

_client: redis.Redis | None = None


class JobResult(BaseModel):
    """What a caller gets back when polling for a job.

    `report` is left as a plain dict rather than typed as `Report`: this module is about
    moving bytes between processes, and teaching it the agent layer's schema would tie the
    queue to what the orchestrator happens to return today.
    """

    job_id: str
    status: Literal["running", "done", "failed"]
    report: dict[str, Any] | None = None
    spent_usd: str | None = None
    error: str | None = None


def _key(job_id: str) -> str:
    return f"mycel:result:{job_id}"


async def get_client() -> redis.Redis:
    """The process-wide client, opened on first use.

    Not at import: importing this module must not require Redis to be up, or every test
    and every `--help` needs docker running.
    """
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_client() -> None:
    """Close it on the way out. Safe when nothing was ever opened."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def mark_running(job_id: str) -> None:
    """Record that a worker has picked this job up.

    Written by the worker rather than the producer, so the state reflects what is actually
    happening rather than what was hoped for at publish time.
    """
    await _write(JobResult(job_id=job_id, status="running"))


async def store(job_id: str, report: BaseModel, spent_usd: str) -> None:
    """Record a finished report."""
    await _write(
        JobResult(
            job_id=job_id,
            status="done",
            report=report.model_dump(mode="json"),
            spent_usd=spent_usd,
        )
    )


async def store_failure(job_id: str, error: str) -> None:
    """Record that a job is not coming back.

    Written only once a job is out of retries. Writing it on every failed attempt would
    show a caller `failed` for a job that is about to be tried again.
    """
    await _write(JobResult(job_id=job_id, status="failed", error=error[:500]))


async def fetch(job_id: str) -> JobResult | None:
    """Read a job's state, or `None` when nothing is known about it.

    `None` covers both "never existed" and "expired", which are the same thing to a caller:
    there is nothing to show either way, and pretending to tell them apart would require
    keeping a record this module has just said it does not keep.
    """
    client = await get_client()
    raw = await client.get(_key(job_id))
    if raw is None:
        return None
    return JobResult.model_validate(json.loads(raw))


async def _write(result: JobResult) -> None:
    """One write path, so every state gets the same TTL.

    The TTL is refreshed on each write rather than set once at `running`: a job that runs
    for most of the window would otherwise have its finished report expire moments after
    being stored.
    """
    client = await get_client()
    await client.set(
        _key(result.job_id),
        result.model_dump_json(),
        ex=get_settings().result_ttl_seconds,
    )
