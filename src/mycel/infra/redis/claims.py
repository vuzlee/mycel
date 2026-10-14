"""One worker at a time per job: a second delivery of a job still running is not run again."""

from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client


async def take(job_id: str, ttl_seconds: int) -> bool:
    """True if this worker now holds the job; False if another one is running it."""
    client = await get_client()
    return bool(await client.set(_kv.key("claim", job_id), "1", nx=True, ex=ttl_seconds))


async def release(job_id: str) -> None:
    client = await get_client()
    await client.delete(_kv.key("claim", job_id))
