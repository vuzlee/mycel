"""Shared test fixtures.

The module-level `ALLOW_MODEL_REQUESTS = False` is the important line: it makes any real
provider call raise instead of going out to the network. A test suite that can spend money
is a test suite nobody runs.
"""

import asyncio
import os
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from dotenv import dotenv_values
from pydantic_ai import models

from mycel.core.config import Settings, get_settings

# No test may reach a real model, whatever else it does.
models.ALLOW_MODEL_REQUESTS = False

TEST_DB_SUFFIX = "_test"


def _with_database(dsn: str, name: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _database_of(dsn: str) -> str:
    return urlsplit(dsn).path.lstrip("/")


async def _create_if_missing(dsn: str) -> None:
    """Create the test database, connecting to `postgres` because you cannot create your own."""
    name = _database_of(dsn)
    conn = await asyncpg.connect(_with_database(dsn, "postgres"))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _resolve_test_dsn() -> str | None:
    """The suite's own database, beside the developer's — never the developer's.

    Every Postgres test drops its schemas on teardown, so pointing them at the dev database
    would wipe it. The server is a property of the machine and comes from the environment or
    `.env`; the database name is this suite's, always ending in `_test`. Unreachable server
    means the Postgres tests skip, which is right on a machine with no database.
    """
    dsn = os.environ.get("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL")
    if not dsn:
        return None

    name = _database_of(dsn)
    test_dsn = dsn if name.endswith(TEST_DB_SUFFIX) else _with_database(dsn, name + TEST_DB_SUFFIX)
    try:
        asyncio.run(_create_if_missing(test_dsn))
    except OSError:
        return None
    return test_dsn


_TEST_DSN = _resolve_test_dsn()
if _TEST_DSN:
    os.environ["DATABASE_URL"] = _TEST_DSN
else:
    os.environ.pop("DATABASE_URL", None)

# Variables that would otherwise leak a developer's real environment into the tests. A
# machine with a live ANTHROPIC_API_KEY must not behave differently from CI.
_LEAKY_PREFIXES = ("MYCEL_", "ANTHROPIC_", "OTEL_", "LOCAL_LLM_", "LOG_")


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only; we do not support trio."""
    return "asyncio"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip inherited env vars and reset the settings cache around every test.

    Also stops `Settings` reading the developer's `.env`, so the suite sees defaults
    unless a test sets a variable itself.
    """
    for key in list(os.environ):
        if key.startswith(_LEAKY_PREFIXES):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
