"""Postgres: schema."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from mycel.infra.postgres.engine import async_dsn, dispose_engine
from mycel.infra.postgres.locks import try_lock
from mycel.infra.postgres.models import Base
from tests.fakes import DSN, needs_postgres
from tests.pg import (
    _PG,
)

pytestmark = pytest.mark.anyio


class TestTheAsyncDsn:
    def test_a_plain_dsn_gets_the_async_driver(self) -> None:
        assert async_dsn("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"

    def test_an_explicit_driver_is_left_alone(self) -> None:
        """A deployment that names its own driver means it."""
        assert async_dsn("postgresql+psycopg://h/db") == "postgresql+psycopg://h/db"


@needs_postgres
class TestTheMigration:
    """`create_all` and `alembic upgrade head` must build the same thing."""

    @pytest.mark.parametrize(
        ("schema", "table"),
        [
            ("bronze", "jira_issue"),
            ("bronze", "jira_worklog"),
            ("silver", "work_item"),
            ("silver", "worklog"),
            ("gold", "work_item"),
            ("gold", "worklog"),
            ("app", "user"),
            ("app", "session"),
            ("app", "conversation"),
            ("app", "turn"),
            ("app", "document"),
            ("app", "chunk"),
        ],
    )
    async def test_upgrade_builds_what_the_models_declare(
        self, alembic: Config, schema: str, table: str
    ) -> None:
        await asyncio.to_thread(command.upgrade, alembic, "head")

        engine = create_async_engine(async_dsn(DSN))
        async with engine.connect() as conn:
            built = await conn.run_sync(
                lambda sync: {
                    c["name"]: c["type"].compile(_PG)
                    for c in inspect(sync).get_columns(table, schema=schema)
                }
            )
        await engine.dispose()

        # Compiled for postgresql: generic `str(type)` prints DATETIME, not TIMESTAMP.
        declared = {
            c.name: c.type.compile(_PG) for c in Base.metadata.tables[f"{schema}.{table}"].columns
        }
        assert built == declared

    @pytest.mark.parametrize(
        ("schema", "table"),
        [
            ("bronze", "telegram_message"),
            ("gold", "progress_update"),
            ("silver", "message"),
        ],
    )
    async def test_the_hashtag_tables_are_gone(
        self, alembic: Config, schema: str, table: str
    ) -> None:
        """Dropped rather than deprecated — 0004 for the first two, 0005 for `silver.message`."""
        await asyncio.to_thread(command.upgrade, alembic, "head")

        engine = create_async_engine(async_dsn(DSN))
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync: inspect(sync).get_table_names(schema=schema))
        await engine.dispose()
        assert table not in names

    async def test_downgrade_leaves_nothing_behind(self, alembic: Config) -> None:
        """Written while the tables are empty, because nobody writes one later."""
        await asyncio.to_thread(command.upgrade, alembic, "head")
        await asyncio.to_thread(command.downgrade, alembic, "base")

        engine = create_async_engine(async_dsn(DSN))
        async with engine.connect() as conn:
            remaining = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.schemata "
                    "WHERE schema_name IN ('bronze','silver','gold','app')"
                )
            )
        await engine.dispose()
        assert remaining == 0


@needs_postgres
class TestTheAdvisoryLock:
    """Two schedulers, one sync. The loser skips rather than queueing identical work."""

    @pytest.fixture(autouse=True)
    async def _own_engine(self) -> AsyncIterator[None]:
        """A fresh process-wide engine per test, because each test gets its own loop."""
        await dispose_engine()
        yield
        await dispose_engine()

    async def test_a_lock_is_granted(self) -> None:
        async with try_lock("test:sync") as acquired:
            assert acquired

    async def test_a_second_holder_is_refused(self) -> None:
        async with try_lock("test:sync") as first, try_lock("test:sync") as second:
            assert first and not second

    async def test_releasing_lets_the_next_one_in(self) -> None:
        async with try_lock("test:sync") as first:
            assert first
        async with try_lock("test:sync") as again:
            assert again

    async def test_unrelated_names_do_not_contend(self) -> None:
        async with try_lock("test:sync") as first, try_lock("test:report") as other:
            assert first and other
