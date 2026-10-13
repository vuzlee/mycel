"""Gold is embedded on the ingest worker; a sync only queues the job."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from mycel import worker
from mycel.domains import index, sync
from mycel.queue import producer, topology
from mycel.queue.job import INGEST_KINDS, Job, JobKind
from mycel.services import access, enqueue

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _no_session() -> AsyncIterator[None]:
    yield None


async def test_a_sync_queues_one_index_job_and_embeds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged: list[Job] = []
    sent: list[Job] = []

    async def stage(session: object, job: Job) -> Job:
        staged.append(job)
        return job

    async def send(job: Job) -> None:
        sent.append(job)

    async def fetched(*_: Any, **__: Any) -> Any:
        return SimpleNamespace(issues=1, keys=["MYC-1"])

    async def transformed(*_: Any, **__: Any) -> Any:
        return SimpleNamespace(silver_items=1, silver_worklogs=0, items=1, worklogs=0)

    async def nothing(*_: Any, **__: Any) -> int:
        return 0

    def no_embedding(*_: Any) -> None:
        raise AssertionError("the scheduler loaded the embedder")

    monkeypatch.setattr(sync, "session_scope", _no_session)
    monkeypatch.setattr(sync, "fetch_jira", fetched)
    monkeypatch.setattr(sync, "transform", transformed)
    monkeypatch.setattr(sync, "_record", nothing)
    monkeypatch.setattr(access, "refresh_everyone", nothing)
    monkeypatch.setattr(sync, "service_auth", lambda: None)
    monkeypatch.setattr(enqueue, "stage", stage)
    monkeypatch.setattr(enqueue, "send", send)
    monkeypatch.setattr(index, "run", no_embedding)

    await sync.sync_jira()

    assert [j.kind for j in staged] == [JobKind.INDEX_GOLD]
    assert sent == staged


def test_the_index_job_runs_on_the_ingest_worker() -> None:
    job = Job(kind=JobKind.INDEX_GOLD)
    assert JobKind.INDEX_GOLD in INGEST_KINDS
    assert producer.queue_for(job) == topology.INGEST_QUEUE


async def test_the_worker_routes_the_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Job] = []

    async def run(job: Job) -> None:
        ran.append(job)

    monkeypatch.setattr(index, "run", run)
    job = Job(kind=JobKind.INDEX_GOLD)
    await worker.run(job)
    assert ran == [job]


async def test_without_qdrant_the_job_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(index, "configured", lambda: False)
    monkeypatch.setattr(index, "session_scope", None)
    await index.run(Job(kind=JobKind.INDEX_GOLD))
