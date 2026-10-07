"""Small stand-ins shared by several test files."""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mycel.core.config import get_settings
from mycel.infra.postgres.engine import async_dsn
from mycel.infra.postgres.models import Base
from mycel.sources import google_calendar

#: The suite's own database, set by `conftest.py`. Empty means the Postgres tests skip.
DSN = os.environ.get("DATABASE_URL", "")
needs_postgres = pytest.mark.skipif(not DSN, reason="no test database is reachable")
SCHEMAS = ("bronze", "silver", "gold", "app")


class FakeRedis:
    """Enough of the client for a state round or a draft: set with a TTL, and read-and-delete.

    The TTL is recorded rather than honoured — nothing here waits, and what a test wants to
    know is that an expiry was asked for at all.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


@pytest.fixture
def bangkok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not UTC, so a dropped `timeZone` or a host-zone reading shows up as a wrong hour."""
    monkeypatch.setenv("TIMEZONE", "Asia/Bangkok")
    get_settings.cache_clear()


@pytest.fixture
def google_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The grant is `services/google_oauth.py`'s; here it is a string in a header."""

    async def _token(user_id: int) -> str:
        return "access-token"

    monkeypatch.setattr(google_calendar, "token_for", _token)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A schema built from the models, dropped again when the test ends.

    Built with `create_all` rather than `alembic upgrade`, so a bug in a migration cannot
    make these pass — `test_postgres.py`'s migration tests hold the two together.
    """
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        async with engine.begin() as conn:
            for schema in SCHEMAS:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await engine.dispose()
