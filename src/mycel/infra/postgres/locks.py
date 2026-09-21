"""Advisory locks: one holder of a named job at a time, across processes.

Postgres rather than a flag in a table, because the lock is released when the connection
dies. A process that is killed mid-sync leaves nothing to clean up, which is the failure a
row-based lock handles worst — the stale row outlives the crash and blocks every run after.

Advisory means Postgres enforces nothing about the data; the meaning of a lock is whatever
the callers agree it is.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import blake2b

from sqlalchemy import text

from mycel.infra.postgres.engine import get_engine


def _key(name: str) -> int:
    """A stable signed 64-bit key for a name, which is all the API takes.

    Hashed rather than enumerated so a new job needs no central registry of numbers. A
    collision would make two unrelated jobs exclude each other; at 64 bits, across the
    handful of names this system will ever have, that is not a risk worth code.
    """
    return int.from_bytes(blake2b(name.encode(), digest_size=8).digest(), "big", signed=True)


@asynccontextmanager
async def try_lock(name: str) -> AsyncIterator[bool]:
    """Hold `name` for the block, or yield False if someone else already does.

    Non-blocking on purpose. A scheduler that waits for the previous run builds a queue of
    identical work; skipping is correct, because the next tick will do it anyway and every
    step downstream is idempotent.

    The lock lives on its own connection for the whole block — a session-level lock
    released by that connection closing, so it cannot outlive the work it guards.
    """
    async with get_engine().connect() as conn:
        acquired = bool(
            await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _key(name)})
        )
        try:
            yield acquired
        finally:
            if acquired:
                await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _key(name)})
