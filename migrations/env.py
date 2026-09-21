"""Alembic entry point.

Reads the DSN from `Settings`, not from `alembic.ini`, so a migration cannot run against a
different database than the application. Runs async, for the same reason the engine does.

`alembic_version` stays in `public`: it is alembic's own bookkeeping, and a per-layer
schema cannot hold it when the first migration is what creates that schema.
"""

import asyncio

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


def run_offline() -> None:
    """Emit SQL to stdout, for a DBA who applies migrations by hand."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        include_schemas=True,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _migrate(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    """Apply migrations against a live database."""
    engine = async_engine_from_config(
        {"sqlalchemy.url": async_dsn(get_settings().database_url)},
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
