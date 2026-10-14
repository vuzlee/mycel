"""The handler tasks a worker is running, so a stop can wait for them."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class InFlight:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[object]] = set()

    def __len__(self) -> int:
        return len(self._tasks)

    def track(
        self, handler: Callable[[T], Coroutine[Any, Any, None]]
    ) -> Callable[[T], Coroutine[Any, Any, None]]:
        """`handler`, with each call counted while it runs."""

        async def tracked(arg: T) -> None:
            task = asyncio.current_task()
            if task is not None:
                self._tasks.add(task)
            try:
                await handler(arg)
            finally:
                if task is not None:
                    self._tasks.discard(task)

        return tracked

    async def drain(self, timeout: float) -> int:
        """Wait up to `timeout` seconds for every tracked call; how many were still running."""
        pending = set(self._tasks)
        if pending:
            _, pending = await asyncio.wait(pending, timeout=timeout)
        return len(pending)
