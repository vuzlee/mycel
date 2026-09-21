"""The connections to Redis, and the reason there are two of them.

Everything else in this package asks here for a client rather than opening its own, so
there is one place that reads a URL and one pool per process per purpose.

**Two clients, because two eviction policies.** The keys in `results.py`, `budgets.py` and
`streams.py` must not be evicted — an evicted budget reads back as a full ceiling, which
silently refunds a job — so that server runs `noeviction` and is bounded by TTL alone. A
cache is the opposite: it is *supposed* to be dropped under pressure, and sharing an
instance would mean cache growth failing a budget write. `redis_cache_url` exists from the
start, even with nothing caching yet, because splitting it later means touching every call
site.
"""

import redis.asyncio as redis

from mycel.core.config import get_settings

_clients: dict[str, redis.Redis] = {}


async def _client_for(url: str) -> redis.Redis:
    """One client per URL, opened on first use.

    Not at import: importing this package must not require Redis to be up, or every test
    and every `--help` needs docker running.
    """
    if url not in _clients:
        _clients[url] = redis.from_url(url, decode_responses=True)
    return _clients[url]


async def get_client() -> redis.Redis:
    """The client for in-flight state: results, budgets, event streams. `noeviction`."""
    return await _client_for(get_settings().redis_url)


async def get_cache_client() -> redis.Redis:
    """The client for cached values, on a server that is allowed to evict them."""
    return await _client_for(get_settings().redis_cache_url)


async def close_clients() -> None:
    """Close whatever was opened. Safe when nothing ever was."""
    for client in _clients.values():
        await client.aclose()
    _clients.clear()
