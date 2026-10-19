"""Alembic entry point; the DSN comes from Settings, and alembic_version stays in public."""

import asyncio
import os

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from mycel.core.config import get_settings
from mycel.infra.postgres.engine import async_dsn
from mycel.infra.postgres.models import Base

target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        compare_type=True,
    )


def _url() -> str:
    """The owner's URL, since only the owner may change the schema; falls back to the app's."""
    settings = get_settings()
    return settings.migration_database_url


def run_offline() -> None:
    """Emit SQL to stdout instead of applying it."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        include_schemas=True,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _migrate(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        if context.get_context()._migrations_fn.__name__ == "downgrade":
            _refuse_unless_test(connection)
        context.run_migrations()


def _refuse_unless_test(connection: Connection) -> None:
    """A downgrade drops tables: only a `_test` database, or MYCEL_ALLOW_DOWNGRADE=1."""
    database = connection.engine.url.database or ""
    if not database.endswith("_test") and os.environ.get("MYCEL_ALLOW_DOWNGRADE") != "1":
        raise SystemExit(
            f"refusing to downgrade {database!r}; set MYCEL_ALLOW_DOWNGRADE=1 if meant"
        )


async def run_online() -> None:
    engine = async_engine_from_config(
        {"sqlalchemy.url": async_dsn(_url())},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_migrate)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
