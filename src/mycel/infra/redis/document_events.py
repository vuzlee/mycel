"""A per-user signal that one of their documents changed state. Redis pub/sub.

The worker publishes, the API's SSE route listens and re-reads the list from Postgres. The
message carries nothing but "look again": Postgres stays the only place a status is read,
and a missed message costs one refresh, never a wrong status.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from mycel.infra.redis.client import get_client


def _channel(user_id: int) -> str:
    return f"documents:{user_id}"


async def changed(user_id: int) -> None:
    await (await get_client()).publish(_channel(user_id), "changed")


class Listener:
    """A subscription that is live from the moment `open` returns.

    A generator would subscribe only when first iterated, and a change published in that
    gap is lost - the page would then show a document as processing until the next one.
    """

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id
        self._pubsub: Any = None

    async def open(self) -> "Listener":
        self._pubsub = (await get_client()).pubsub()
        await self._pubsub.subscribe(_channel(self._user_id))
        return self

    async def next(self, timeout_s: float) -> bool:
        """True when something changed, False when `timeout_s` passed in silence.

        A loop, because `get_message` returns early with nothing when what it read was the
        subscribe confirmation rather than a message.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while (left := deadline - loop.time()) > 0:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=left)
            if message is not None:
                return True
        return False

    async def close(self) -> None:
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(_channel(self._user_id))
            await self._pubsub.aclose()


async def listen(user_id: int, timeout_s: float) -> AsyncIterator[bool]:
    """Yields True when something changed, False when `timeout_s` passed in silence."""
    listener = await Listener(user_id).open()
    try:
        while True:
            yield await listener.next(timeout_s)
    finally:
        await listener.close()
