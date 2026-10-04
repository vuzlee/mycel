"""The connections to Redis, and the reason there are two of them.

Everything else in this package asks here for a client rather than opening its own, so
there is one place that reads a URL and one pool per purpose.

**Two clients, because two eviction policies.** The keys in `results.py`, `budgets.py` and
`streams.py` must not be evicted — an evicted budget reads back as a full ceiling, which
silently refunds a job — so that server runs `noeviction` and is bounded by TTL alone. A
cache is the opposite: it is *supposed* to be dropped under pressure, and sharing an
instance would mean cache growth failing a budget write. `redis_cache_url` exists from the
start, even with nothing caching yet, because splitting it later means touching every call
site.

**One client per loop, not one per process.** A `redis.Redis` holds a connection pool whose
sockets are bound to the loop that opened them. Handing it to a second loop raises
`got Future attached to a different loop`, and then `Event loop is closed` while it tries
to tear the connection down — a pair of errors that name the transport and say nothing
about the cache key they came from. One process runs several loops in practice: a test
suite starts one per test, and `asyncio.run` in a script starts one per call. So the loop
is part of the key, and an entry whose loop has closed is dropped on the next lookup.
"""

import asyncio

import redis.asyncio as redis

from mycel.core.config import get_settings

#: Keyed by the loop that opened the client as well as the URL — see the module docstring.
_clients: dict[tuple[asyncio.AbstractEventLoop, str], redis.Redis] = {}


def _forget_dead_loops() -> None:
    """Drop clients whose loop has closed, which is the only way they are ever unusable.

    Not closed first: `aclose()` needs the loop it was opened on, and that loop is gone.
    The sockets go when the transports are collected.
    """
    for key in [key for key in _clients if key[0].is_closed()]:
        del _clients[key]


async def _client_for(url: str) -> redis.Redis:
    """One client per loop per URL, opened on first use.

    Not at import: importing this package must not require Redis to be up, or every test
    and every `--help` needs docker running.
    """
    _forget_dead_loops()
    key = (asyncio.get_running_loop(), url)
    if key not in _clients:
        _clients[key] = redis.from_url(url, decode_responses=True)
    return _clients[key]


async def get_client() -> redis.Redis:
    """The client for in-flight state: results, budgets, event streams. `noeviction`."""
    return await _client_for(get_settings().redis_url)


async def get_cache_client() -> redis.Redis:
    """The client for cached values, on a server that is allowed to evict them."""
    return await _client_for(get_settings().redis_cache_url)


async def close_clients() -> None:
    """Close what this loop opened. Safe when nothing ever was.

    Only this loop's clients: awaiting `aclose()` on another loop's client is the very
    failure the keying avoids. Clients belonging to loops that have ended are dropped.
    """
    _forget_dead_loops()
    loop = asyncio.get_running_loop()
    for key, client in list(_clients.items()):
        if key[0] is loop:
            await client.aclose()
            del _clients[key]
