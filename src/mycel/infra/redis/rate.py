"""Sliding-window rate counters, on the state Redis."""

import math
import time
from dataclasses import dataclass

from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client

WINDOW_SECONDS = 60


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    #: Seconds until a refused caller would be let through; 0 when allowed.
    retry_after: int


async def hit(scope: str, key: str, limit: int, now: float | None = None) -> Verdict:
    """Count one request against the last `WINDOW_SECONDS`, not the calendar minute.

    The previous minute counts in proportion to how much of it is still inside the window,
    so ten calls at :59 and ten at :00 are twenty, not two tens.
    """
    now = time.time() if now is None else now
    window = int(now // WINDOW_SECONDS)
    into = (now % WINDOW_SECONDS) / WINDOW_SECONDS
    current, previous = _name(scope, key, window), _name(scope, key, window - 1)

    async with (await get_client()).pipeline(transaction=True) as pipe:
        pipe.incr(current)
        pipe.expire(current, 2 * WINDOW_SECONDS, nx=True)
        pipe.get(previous)
        count, _, before = await pipe.execute()

    weighted = int(before or 0) * (1 - into) + int(count)
    if weighted <= limit:
        return Verdict(True, 0)
    return Verdict(False, _wait(int(before or 0), int(count), into, limit))


def _wait(before: int, count: int, into: float, limit: int) -> int:
    """Seconds until `before * (1 - t) + count` falls to `limit`, within this window."""
    if count > limit or before == 0:
        # Only the next window's start helps.
        return max(1, math.ceil((1 - into) * WINDOW_SECONDS))
    target = 1 - (limit - count) / before
    return max(1, math.ceil((target - into) * WINDOW_SECONDS))


def _name(scope: str, key: str, window: int) -> str:
    return _kv.key("rate", scope, key, window)
