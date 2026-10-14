"""What the scheduler publishes about queues and the state Redis, and how long attempts take."""

from typing import Any

import pytest
from prometheus_client import REGISTRY

from mycel.infra.redis import results
from mycel.queue import consumer
from mycel.queue.handler import Handler
from mycel.queue.job import Job, JobKind
from mycel.scheduler import runner
from tests.test_queue import FakeExchange, FakeMessage

pytestmark = pytest.mark.anyio


def _value(name: str, **labels: str) -> float | None:
    return REGISTRY.get_sample_value(name, labels)


async def test_backlog_consumers_and_redis_fill_are_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def depths() -> dict[str, int]:
        return {"jobs.dlq": 0}

    async def work_queues() -> dict[str, tuple[int, int]]:
        return {"jobs": (25, 0), "ingest": (0, 1)}

    class Redis:
        async def info(self, section: str) -> dict[str, Any]:
            return {"used_memory": 200, "maxmemory": 1000}

    async def client() -> Redis:
        return Redis()

    monkeypatch.setattr(runner, "depths", depths)
    monkeypatch.setattr(runner, "work_queues", work_queues)
    monkeypatch.setattr(runner, "get_client", client)

    await runner._count_queues()

    assert _value("mycel_queue_ready", queue="jobs") == 25
    assert _value("mycel_queue_consumers", queue="jobs") == 0
    assert _value("mycel_redis_memory_ratio") == 0.2


async def test_each_attempt_is_timed_with_how_it_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fails(job: Job) -> None:
        raise ValueError("bug")

    async def nothing(*args: Any) -> None:
        pass

    monkeypatch.setattr(results, "mark_running", nothing)
    jobs = Handler(run=fails, record_failure=nothing, final=(), transient=())
    before = _value("mycel_job_attempt_seconds_count", kind="index_gold", outcome="failed") or 0
    job = Job(kind=JobKind.INDEX_GOLD, payload={})

    await consumer.handle(FakeMessage(job.model_dump_json().encode()), FakeExchange(), jobs)  # type: ignore[arg-type]

    after = _value("mycel_job_attempt_seconds_count", kind="index_gold", outcome="failed")
    assert after == before + 1
