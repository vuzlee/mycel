"""Shared test fixtures."""

import asyncio
import os
import socket
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from dotenv import dotenv_values
from pydantic_ai import models

from mycel.core.config import Settings, get_settings

pytest_plugins = ["tests.fakes"]

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
    """The suite's own database, beside the developer's — never the developer's."""
    # The owner, not the app role: the suite runs DDL.
    env = dotenv_values(".env")
    dsn = (
        os.environ.get("MIGRATION_DATABASE_URL")
        or env.get("MIGRATION_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or env.get("DATABASE_URL")
    )
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
os.environ.pop("MIGRATION_DATABASE_URL", None)
os.environ.pop("MYCEL_APP_PASSWORD", None)
if _TEST_DSN:
    os.environ["DATABASE_URL"] = _TEST_DSN
else:
    os.environ.pop("DATABASE_URL", None)

# Variables that would otherwise leak a developer's real environment into the tests. A
_LEAKY_PREFIXES = ("MYCEL_", "GEMINI_", "OTEL_", "LOG_")


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only; we do not support trio."""
    return "asyncio"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip inherited env vars and reset the settings cache around every test."""
    for key in list(os.environ):
        if key.startswith(_LEAKY_PREFIXES):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    # A free METRICS_PORT, so a running dev stack on 9103 does not break app tests.
    monkeypatch.setenv("METRICS_PORT", str(_free_port() - 3))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
