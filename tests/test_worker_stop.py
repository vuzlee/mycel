"""Stopping a worker: jobs in flight finish before the channel closes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from mycel.core.config import get_settings
from mycel.queue import consumer, topology
from mycel.queue.inflight import InFlight

pytestmark = pytest.mark.anyio


class _Queue:
    """Hands one message to the consumer callback, and records the cancel."""

    def __init__(self) -> None:
        self.callback: Any = None
        self.cancelled = False

    async def consume(self, callback: Any, no_ack: bool) -> str:
        self.callback = callback
        return "tag-1"

    async def cancel(self, tag: str) -> None:
        self.cancelled = True


class _Channel:
    async def set_qos(self, prefetch_count: int) -> None:
        pass


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> tuple[_Queue, list[str]]:
    queue = _Queue()
    events: list[str] = []

    @asynccontextmanager
    async def channel() -> AsyncIterator[_Channel]:
        yield _Channel()
        events.append("closed")

    async def declare(ch: Any) -> Any:
        return type("T", (), {"jobs": queue, "ingest": queue, "dlx": None})()

    monkeypatch.setattr(consumer, "channel", channel)
    monkeypatch.setattr(topology, "declare", declare)
    return queue, events


async def test_a_job_in_flight_finishes_before_the_channel_closes(
    monkeypatch: pytest.MonkeyPatch, broker: tuple[_Queue, list[str]]
) -> None:
    """Closing the channel cancels handlers: a deploy would pay for the run twice."""
    queue, events = broker
    started = asyncio.Event()

    async def slow(message: Any, dlx: Any, jobs: Any) -> None:
        started.set()
        await asyncio.sleep(0.2)
        events.append("job done")

    monkeypatch.setattr(consumer, "handle", slow)
    stop = asyncio.Event()
    worker = asyncio.create_task(consumer.run_worker(None, stop))  # type: ignore[arg-type]
    while queue.callback is None:
        await asyncio.sleep(0)

    job = asyncio.create_task(queue.callback(object()))
    await started.wait()
    stop.set()
    await worker

    assert queue.cancelled
    assert events == ["job done", "closed"]
    await job


async def test_the_ingest_worker_says_when_it_stopped_to_recycle(
    monkeypatch: pytest.MonkeyPatch, broker: tuple[_Queue, list[str]]
) -> None:
    queue, _ = broker

    async def quick(message: Any, dlx: Any, jobs: Any) -> None:
        pass

    monkeypatch.setattr(consumer, "handle", quick)
    monkeypatch.setenv("INGEST_WORKER_MAX_JOBS", "1")
    get_settings.cache_clear()
    worker = asyncio.create_task(
        consumer.run_worker(None, asyncio.Event(), topology.INGEST_QUEUE)  # type: ignore[arg-type]
    )
    while queue.callback is None:
        await asyncio.sleep(0)
    await queue.callback(object())

    assert await asyncio.wait_for(worker, timeout=1) is True


async def test_drain_reports_what_outlived_the_deadline() -> None:
    inflight = InFlight()
    never = asyncio.Event()

    async def stuck(_: object) -> None:
        await never.wait()

    task = asyncio.create_task(inflight.track(stuck)(None))
    await asyncio.sleep(0)

    assert len(inflight) == 1
    assert await inflight.drain(0.01) == 1
    task.cancel()
