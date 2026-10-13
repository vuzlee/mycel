"""Fixed-window counters for rate limits, on the state Redis."""

import time

from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client

WINDOW_SECONDS = 60


async def hit(scope: str, key: str) -> tuple[int, int]:
    """Count one request in the current window; `(count, seconds left in the window)`."""
    now = int(time.time())
    window = now // WINDOW_SECONDS
    name = _kv.key("rate", scope, key, window)
    async with (await get_client()).pipeline(transaction=True) as pipe:
        pipe.incr(name)
        pipe.expire(name, WINDOW_SECONDS, nx=True)
        count, _ = await pipe.execute()
    return int(count), WINDOW_SECONDS - now % WINDOW_SECONDS
