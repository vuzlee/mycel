from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mycel.queue.job import Job


@dataclass(frozen=True)
class Handler:
    """What the consumer needs from the app: run a job, record a failure, which errors retry."""

    run: Callable[[Job], Awaitable[None]]
    record_failure: Callable[[Job, str], Awaitable[None]]
    final: tuple[type[Exception], ...]
    transient: tuple[type[Exception], ...]
