"""One question, all the way through: HTTP → broker → worker → Redis → Postgres → HTTP."""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import mycel.agents.core.runner as runner
from mycel.agents.specialists.orchestrator import Orchestrator
from mycel.api.app import create_app
from mycel.core.config import Settings, get_settings
from mycel.infra.postgres.engine import async_dsn, get_engine
from mycel.infra.postgres.models import Base
from mycel.infra.redis.client import close_clients
from mycel.queue import topology
from mycel.queue.connection import channel, close_connection
from mycel.queue.consumer import run_worker
from mycel.worker import HANDLER

pytestmark = pytest.mark.anyio

DSN = os.environ.get("DATABASE_URL", "")
BROKER = os.environ.get("RABBITMQ_URL", "")
CACHE = os.environ.get("REDIS_URL", "")

needs_everything = pytest.mark.skipif(
    not (DSN and BROKER and CACHE), reason="needs postgres, rabbitmq and redis together"
)


SCHEMAS = ("bronze", "silver", "gold", "app")

EMAIL = "e2e@example.com"
PASSWORD = "correct horse battery"
ANSWER = "Two stories shipped and one is overdue."

#: Long enough to tell a worker that never picked the job up from a slow one.
TIMEOUT_SECONDS = 20.0


@pytest.fixture
async def stack(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """The app and a worker, both against the real services, on one loop."""
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("RABBITMQ_URL", BROKER)
    monkeypatch.setenv("REDIS_URL", CACHE)
    get_settings.cache_clear()
    get_engine.cache_clear()

    await _reset_schema()
    await _purge_queues()

    async def _answer(*args: object, **kwargs: object) -> str:
        return ANSWER

    # The one stub is the model, and `build` with it.
    monkeypatch.setattr(runner, "run", _answer)
    monkeypatch.setattr(Orchestrator, "build", classmethod(lambda cls, s: None))

    stop = asyncio.Event()
    worker = asyncio.create_task(run_worker(HANDLER, stop))

    app = create_app(Settings(otel_enabled=False))
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://e2e") as client:
            yield client
    finally:
        stop.set()
        await asyncio.wait_for(worker, timeout=5)
        await close_connection()
        await close_clients()
        await _drop_schema()


async def _sign_in(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    signed_in = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert signed_in.status_code == 200


async def _poll(client: AsyncClient, job_id: str) -> dict[str, object]:
    """Read the job the way the UI does, until it stops saying `running`."""
    waited = 0.0
    while waited < TIMEOUT_SECONDS:
        response = await client.get(f"/chat/{job_id}")
        if response.status_code == 200 and response.json()["status"] != "running":
            return dict(response.json())
        await asyncio.sleep(0.1)
        waited += 0.1
    raise AssertionError(f"job {job_id} never finished — is the worker consuming?")


@needs_everything
class TestOneQuestionAllTheWay:
    async def test_the_answer_comes_back_under_the_id_the_api_gave(
        self, stack: AsyncClient
    ) -> None:
        """The whole point of the job id."""
        await _sign_in(stack)

        queued = await stack.post("/chat", json={"question": "how is the quarter going?"})
        assert queued.status_code == 202
        job_id = queued.json()["job_id"]

        finished = await _poll(stack, job_id)
        assert finished["status"] == "done"
        assert finished["answer"] == ANSWER

    async def test_the_answer_lands_in_the_thread_opened_at_queue_time(
        self, stack: AsyncClient
    ) -> None:
        """The thread exists before the job does."""
        await _sign_in(stack)

        queued = await stack.post("/chat", json={"question": "did anything ship?"})
        conversation_id = queued.json()["conversation_id"]

        finished = await _poll(stack, queued.json()["job_id"])
        assert finished["conversation_id"] == conversation_id
        assert finished["question"] == "did anything ship?"

    async def test_a_follow_up_joins_the_same_thread(self, stack: AsyncClient) -> None:
        await _sign_in(stack)

        first = await stack.post("/chat", json={"question": "how is the quarter going?"})
        thread = first.json()["conversation_id"]
        await _poll(stack, first.json()["job_id"])

        second = await stack.post(
            "/chat", json={"question": "and the one before?", "conversation_id": thread}
        )
        assert second.json()["conversation_id"] == thread
        assert (await _poll(stack, second.json()["job_id"]))["status"] == "done"

    async def test_the_run_survives_redis_forgetting_it(self, stack: AsyncClient) -> None:
        """Redis is a holding area with a TTL; `app.turn` is the record."""
        await _sign_in(stack)
        queued = await stack.post("/chat", json={"question": "what is overdue?"})
        job_id = queued.json()["job_id"]
        await _poll(stack, job_id)

        from mycel.infra.redis.client import get_client

        await (await get_client()).delete(f"mycel:result:{job_id}")

        kept = await stack.get(f"/chat/{job_id}")
        assert kept.status_code == 200
        assert kept.json()["answer"] == ANSWER


async def _reset_schema() -> None:
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _drop_schema() -> None:
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    await engine.dispose()


async def _purge_queues() -> None:
    """Leftovers from an earlier run would be consumed by this one's worker."""
    async with channel() as ch:
        topo = await topology.declare(ch)
        for queue in (topo.jobs, topo.retry, topo.dead):
            await queue.purge()
