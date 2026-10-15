"""One shared HTTP client per event loop, so calls reuse connections."""

import asyncio

import httpx2

_clients: dict[asyncio.AbstractEventLoop, httpx2.AsyncClient] = {}


def shared() -> httpx2.AsyncClient:
    """This loop's client; callers pass their own timeout and headers per request."""
    for loop in [loop for loop in _clients if loop.is_closed()]:
        del _clients[loop]
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        _clients[loop] = httpx2.AsyncClient()
    return _clients[loop]


async def close_clients() -> None:
    """Close this loop's client; the next call opens a fresh one."""
    client = _clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()
