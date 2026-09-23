"""A job's spend, kept where every process running that job can see it.

`JobBudget` counts money inside one process. That is enough while a job is one run in one
process, and it stopped being enough the moment 004 put the work behind a queue:

  * a failed job is retried up to `topology.MAX_ATTEMPTS` times, and each attempt used to
    build a fresh `JobBudget` — so a $0.50 ceiling bought $1.50 of model calls
  * a job whose channel times out is redelivered while the first attempt may still be
    running, and neither copy could see what the other had spent

So the running total lives in Redis under the `job_id`, and the in-process `JobBudget` is
seeded from it at the start of an attempt and written back at the end. The ceiling is then
per *job*, which is what the word was always supposed to mean.

**Writes take the larger of the two values, never the newer.** Redelivery is the case this
exists for, and a plain overwrite loses the larger figure exactly when two copies are
running — the moment it matters most. The comparison happens inside Redis so two writers
cannot interleave between the read and the write.

The key expires: a budget is bookkeeping for a job in flight, not a record of what was
spent. Anything that needs to be kept belongs in Postgres when it exists.

**Why the server runs `noeviction`.** Under `allkeys-lru` memory pressure evicts this
key, and an evicted budget reads back as a full ceiling — the job silently gets its money
back. Every key on that instance carries a TTL, so memory is bounded by expiry instead,
and a write that will not fit fails loudly.
"""

from decimal import Decimal

from mycel.core.config import get_settings
from mycel.infra.redis.client import get_client
from mycel.llm.budget import JobBudget

#: Take the larger figure, refresh the expiry, and do both without a gap another writer
#: could slip into. `spent_usd` is compared as a float and stored as the exact string it
#: arrived as: Lua has no decimal type, and the comparison only has to pick a winner.
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
    """The budget an attempt should start from.

    A job nobody has spent against yet reads back as a full ceiling, which is also what
    happens after the key expires. That is the safe direction to be wrong in only because
    the TTL outlasts the whole retry chain by a wide margin — shorten it and an old job
    silently gets its money back.
    """
    client = await get_client()
    # `str()` on each field rather than trusting `decode_responses`: the client is shared
    # with the rest of the package, and a budget read against a byte-mode client would
    # otherwise fail inside `Decimal` with a message about the wrong thing entirely.
    raw = {str(k): str(v) for k, v in (await client.hgetall(_key(job_id))).items()}
    return JobBudget(
        job_id=job_id,
        ceiling_usd=Decimal(ceiling_usd),
        spent_usd=Decimal(raw.get("spent_usd", "0")),
        tokens=int(raw.get("tokens", "0")),
        requests=int(raw.get("requests", "0")),
    )


async def save(budget: JobBudget) -> None:
    """Publish what this attempt spent, keeping whichever total is larger.

    Called in a `finally`: a run that was stopped by its own limits, or that raised
    half-way, has already spent real money, and an attempt that does not record its spend
    hands the next attempt a clean slate it did not earn.
    """
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
