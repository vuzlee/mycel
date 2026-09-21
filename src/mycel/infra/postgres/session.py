"""A session's lifetime: commit on success, rollback on error, always close.

One unit of work = one session. Never share one across concurrent tasks — SQLAlchemy
sessions are not concurrency-safe, and two tasks on one session corrupt its identity map
rather than raising.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mycel.infra.postgres.engine import get_engine


def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    # Built per call rather than cached: it is cheap, and a cached one would outlive the
    # engine that `dispose_engine()` throws away.
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Open a session, commit if the block succeeds, roll back if it raises."""
    async with _sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, with the same commit rule."""
    async with session_scope() as session:
        yield session
