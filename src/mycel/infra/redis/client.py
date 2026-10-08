"""Redis clients: one for in-flight state (noeviction), one for an evicting cache, per loop."""

import asyncio

import redis.asyncio as redis

from mycel.core.config import get_settings

#: Keyed by event loop and URL: a client is only usable on the loop that opened it.
_clients: dict[tuple[asyncio.AbstractEventLoop, str], redis.Redis] = {}


def _forget_dead_loops() -> None:
    """Drop clients whose loop has closed; they cannot be closed without that loop."""
    for key in [key for key in _clients if key[0].is_closed()]:
        del _clients[key]


async def _client_for(url: str) -> redis.Redis:
    """One client per loop per URL, opened on first use, not at import."""
    _forget_dead_loops()
    key = (asyncio.get_running_loop(), url)
    if key not in _clients:
        _clients[key] = redis.from_url(url, decode_responses=True)
    return _clients[key]


async def get_client() -> redis.Redis:
    """The client for in-flight state: results, budgets, event streams. `noeviction`."""
    return await _client_for(get_settings().redis_url)


async def get_cache_client() -> redis.Redis:
    """The client for cached values, on a server allowed to evict them."""
    return await _client_for(get_settings().redis_cache_url)


async def close_clients() -> None:
    """Close this loop's clients and drop those of closed loops."""
    _forget_dead_loops()
    loop = asyncio.get_running_loop()
    for key, client in list(_clients.items()):
        if key[0] is loop:
            await client.aclose()
            del _clients[key]
