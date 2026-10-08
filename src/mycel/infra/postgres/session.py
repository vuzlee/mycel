"""A session's lifetime: commit on success, roll back on error, always close."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mycel.infra.postgres.engine import get_engine


def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    # Built per call: a cached one would outlive the engine `dispose_engine()` drops.
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with _sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
