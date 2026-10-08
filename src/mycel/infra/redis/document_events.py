"""Per-user pub/sub signal that a document changed; listeners re-read Postgres."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from mycel.infra.redis.client import get_client


def _channel(user_id: int) -> str:
    return f"documents:{user_id}"


async def changed(user_id: int) -> None:
    await (await get_client()).publish(_channel(user_id), "changed")


class Listener:
    """A subscription live from the moment `open` returns, so no change is missed."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id
        self._pubsub: Any = None

    async def open(self) -> "Listener":
        self._pubsub = (await get_client()).pubsub()
        await self._pubsub.subscribe(_channel(self._user_id))
        return self

    async def next(self, timeout_s: float) -> bool:
        """True when something changed, False when `timeout_s` passed in silence."""
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
