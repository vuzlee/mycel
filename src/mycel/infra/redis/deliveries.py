"""How many times the broker has handed a job over: a job that kills its worker is never acked."""

from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client

#: Long enough to outlive every retry delay a job can collect.
TTL_SECONDS = 24 * 3600


async def count(job_id: str) -> int:
    """Add this delivery and return the total so far."""
    client = await get_client()
    name = _kv.key("deliveries", job_id)
    total = int(await client.incr(name))
    await client.expire(name, TTL_SECONDS)
    return total
