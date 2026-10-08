"""A job's spend in Redis, shared by every process running that job."""

from decimal import Decimal

from mycel.core.config import get_settings
from mycel.infra.redis.client import get_client
from mycel.llm.budget import JobBudget

#: Atomically keep the larger total and refresh the TTL; compared as float, stored as given.
_MERGE = """
local cur = tonumber(redis.call('HGET', KEYS[1], 'spent_usd')) or -1
if tonumber(ARGV[1]) > cur then
  redis.call('HSET', KEYS[1], 'spent_usd', ARGV[1], 'tokens', ARGV[2], 'requests', ARGV[3])
end
redis.call('EXPIRE', KEYS[1], ARGV[4])
"""


def _key(job_id: str) -> str:
    return f"mycel:budget:{job_id}"


async def load(job_id: str, ceiling_usd: Decimal | str) -> JobBudget:
    """The budget an attempt should start from; an unknown job reads as a full ceiling."""
    client = await get_client()
    # str(): the shared client may not decode responses.
    raw = {str(k): str(v) for k, v in (await client.hgetall(_key(job_id))).items()}
    return JobBudget(
        job_id=job_id,
        ceiling_usd=Decimal(ceiling_usd),
        spent_usd=Decimal(raw.get("spent_usd", "0")),
        tokens=int(raw.get("tokens", "0")),
        requests=int(raw.get("requests", "0")),
    )


async def save(budget: JobBudget) -> None:
    """Publish this attempt's spend, keeping the larger total. Call in a `finally`."""
    client = await get_client()
    await client.eval(
        _MERGE,
        1,
        _key(budget.job_id),
        str(budget.spent_usd),
        str(budget.tokens),
        str(budget.requests),
        str(get_settings().result_ttl_seconds),
    )
