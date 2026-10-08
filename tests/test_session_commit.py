"""A request sent the instant login returns is already signed in."""

import asyncio
import os
import socket
import threading
import time
from collections.abc import Iterator

import httpx2
import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mycel.api.app import create_app
from mycel.core.config import Settings
from mycel.infra.postgres.engine import async_dsn, get_engine
from mycel.infra.postgres.models import Base

DSN = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DSN, reason="no test database")
assert not DSN or DSN.rsplit("/", 1)[-1].endswith("_test"), f"refusing to run against {DSN}"
SCHEMAS = ("bronze", "silver", "gold", "app")


async def _schema(create: bool) -> None:
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            verb = "CREATE SCHEMA IF NOT EXISTS" if create else "DROP SCHEMA IF EXISTS"
            await conn.execute(text(f"{verb} {schema}{'' if create else ' CASCADE'}"))
        if create:
            await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server() -> Iterator[str]:
    asyncio.run(_schema(create=True))
    get_engine.cache_clear()
    port = _free_port()
    config = uvicorn.Config(
        create_app(Settings(otel_enabled=False)), port=port, log_level="warning"
    )
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not running.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            pytest.fail("uvicorn did not start within 15s")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        running.should_exit = True
        thread.join(timeout=10)
        get_engine.cache_clear()
        asyncio.run(_schema(create=False))


def test_the_next_request_after_login_is_signed_in(server: str) -> None:
    email, password = "race@example.com", "correct horse battery"
    httpx2.post(f"{server}/auth/register", json={"email": email, "password": password})

    signed_in = 0
    for _ in range(20):
        with httpx2.Client(base_url=server) as client:
            client.post("/auth/login", json={"email": email, "password": password})
            signed_in += client.get("/auth/me").status_code == 200

    assert signed_in == 20
