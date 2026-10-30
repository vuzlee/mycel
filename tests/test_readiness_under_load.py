"""Readiness answers while every request connection is taken."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from mycel.api.app import create_app
from mycel.core.config import Settings, get_settings
from mycel.infra.postgres.engine import dispose_engine, get_engine
from tests.fakes import needs_postgres

pytestmark = [needs_postgres, pytest.mark.anyio]


@pytest.fixture
async def small_pool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setenv("DB_POOL_SIZE", "1")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    get_settings.cache_clear()
    await dispose_engine()
    yield
    await dispose_engine()
    get_settings.cache_clear()


async def test_readiness_does_not_wait_for_a_full_pool(small_pool: None) -> None:
    """A probe queued behind requests timed out and took a busy pod out of the Service."""
    app = create_app(Settings(otel_enabled=False))
    async with get_engine().connect():  # the one request connection, held
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await asyncio.wait_for(client.get("/health/ready"), timeout=3)

    assert response.status_code == 200
