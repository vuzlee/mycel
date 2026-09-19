"""One broker connection per process, opened lazily and shared.

A connection is a TCP socket plus an AMQP handshake. Opening one per publish turns a job
that takes microseconds of work into one that takes a round trip, and leaves the broker
holding hundreds of short-lived connections — the usual reason a healthy RabbitMQ starts
refusing them.

`robust_connect` reconnects on its own after a broker restart and re-declares whatever was
declared through it, which is the whole reason to use aio-pika's robust variant rather than
a plain connection: without it, a broker bounce leaves every worker silently idle.

Callers get a **channel**, not the connection. Channels are the unit AMQP multiplexes over
one socket, and a channel is not safe to share between concurrent publishers — each caller
opens its own and closes it when done.
"""

from types import TracebackType

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from mycel.core.config import get_settings
from mycel.core.logging import get_logger

log = get_logger(__name__)

_connection: AbstractRobustConnection | None = None


async def get_connection() -> AbstractRobustConnection:
    """The process-wide connection, opened on first use.

    Not built at import: importing a module must not require a running broker, or every
    test and every `--help` needs docker up.
    """
    global _connection
    if _connection is None or _connection.is_closed:
        settings = get_settings()
        log.info("connecting to broker", extra={"url": _redact(settings.rabbitmq_url)})
        _connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    return _connection


async def close_connection() -> None:
    """Close it on the way out. Safe to call when nothing was ever opened."""
    global _connection
    if _connection is not None and not _connection.is_closed:
        await _connection.close()
    _connection = None


class channel:
    """`async with channel() as ch:` — a channel of its own, closed on exit.

    A context manager rather than a plain function because a leaked channel is invisible:
    the process keeps working until the broker's per-connection channel limit is reached,
    and only then does everything fail at once.
    """

    def __init__(self) -> None:
        self._channel: aio_pika.abc.AbstractChannel | None = None

    async def __aenter__(self) -> aio_pika.abc.AbstractChannel:
        connection = await get_connection()
        self._channel = await connection.channel()
        return self._channel

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
        self._channel = None


def _redact(url: str) -> str:
    """Strip the password before logging a connection string."""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}"
