"""Advisory locks: one holder of a named job at a time, released when the connection dies."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import blake2b

from sqlalchemy import text

from mycel.infra.postgres.engine import get_engine


def _key(name: str) -> int:
    """A stable signed 64-bit key for a name."""
    return int.from_bytes(blake2b(name.encode(), digest_size=8).digest(), "big", signed=True)


@asynccontextmanager
async def try_lock(name: str) -> AsyncIterator[bool]:
    """Hold `name` for the block, or yield False without waiting if someone else does."""
    async with get_engine().connect() as conn:
        acquired = bool(
            await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _key(name)})
        )
        try:
            yield acquired
        finally:
            if acquired:
                await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _key(name)})
