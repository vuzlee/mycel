"""One worker at a time per job: a second delivery of a job still running is not run again.

A claim is short and renewed while the job runs, so a worker that dies stops renewing and
the job is free again within one TTL, before the retry that would otherwise find it held.
"""

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mycel.core.logging import get_logger
from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client

log = get_logger(__name__)

#: How long a claim outlives its last renewal; under the second retry delay (30 s).
TTL_SECONDS = 25
RENEW_SECONDS = 8

# Renew or release only a claim this holder still owns.
_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class AlreadyRunning(Exception):
    """Another worker holds this job; the copy is retried, and finds it done."""


@asynccontextmanager
async def holding(job_id: str) -> AsyncIterator[None]:
    """Hold the job for the block, renewing it; `AlreadyRunning` if someone else holds it."""
    client = await get_client()
    name = _kv.key("claim", job_id)
    token = secrets.token_hex(8)
    if not await client.set(name, token, nx=True, ex=TTL_SECONDS):
        raise AlreadyRunning(job_id)
    renewer = asyncio.create_task(_renew(name, token))
    try:
        yield
    finally:
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
        await client.eval(_RELEASE, 1, name, token)


async def _renew(name: str, token: str) -> None:
    client = await get_client()
    while True:
        await asyncio.sleep(RENEW_SECONDS)
        try:
            if not await client.eval(_RENEW, 1, name, token, str(TTL_SECONDS)):
                log.warning("claim lost while running", extra={"claim": name})
                return
        except Exception:
            log.warning("could not renew claim", extra={"claim": name}, exc_info=True)
