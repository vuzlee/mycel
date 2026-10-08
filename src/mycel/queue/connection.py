"""One robust broker connection per process, opened lazily; each caller gets its own channel."""

from types import TracebackType

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from mycel.core.config import get_settings
from mycel.core.logging import get_logger

log = get_logger(__name__)

_connection: AbstractRobustConnection | None = None


async def get_connection() -> AbstractRobustConnection:
    """The process-wide connection, opened on first use so imports need no broker."""
    global _connection
    if _connection is None or _connection.is_closed:
        settings = get_settings()
        log.info("connecting to broker", extra={"url": _redact(settings.rabbitmq_url)})
        _connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    return _connection


async def close_connection() -> None:
    """Close the connection; safe when none was opened."""
    global _connection
    if _connection is not None and not _connection.is_closed:
        await _connection.close()
    _connection = None


class channel:
    """A channel of its own, closed on exit."""

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
