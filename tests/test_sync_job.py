"""Connecting Jira queues a sync; a sync already running covers it."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

import mycel.domains.sync as sync
import mycel.services.access as access
import mycel.services.enqueue as enqueue
import mycel.worker as worker
from mycel.plugins.jira import oauth as jira_oauth
from mycel.plugins.jira.plugin import PLUGIN as JIRA
from mycel.queue.job import Job, JobKind

pytestmark = pytest.mark.anyio


def _lock(free: bool):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def lock(name: str) -> AsyncIterator[bool]:
        assert name == sync.LOCK
        yield free

    return lock


async def test_the_worker_runs_a_sync_job(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    async def fake_sync() -> None:
        ran.append("sync")

    monkeypatch.setattr(sync, "try_lock", _lock(True))
    monkeypatch.setattr(sync, "sync_jira", fake_sync)
    await worker.run(Job(kind=JobKind.SYNC_JIRA))
    assert ran == ["sync"]


async def test_a_sync_already_running_covers_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_run() -> None:
        raise AssertionError("ran twice")

    monkeypatch.setattr(sync, "try_lock", _lock(False))
    monkeypatch.setattr(sync, "sync_jira", must_not_run)
    await sync.run(Job(kind=JobKind.SYNC_JIRA))


async def test_connecting_jira_refreshes_access_and_queues_a_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    async def refresh(user_id: int) -> None:
        seen.append(("refresh", user_id))

    async def queue(job: Job) -> None:
        seen.append(job.kind)

    async def connect(*_: object) -> None:
        seen.append("connect")

    monkeypatch.setattr(jira_oauth, "connect", connect)
    monkeypatch.setattr(access, "refresh", refresh)
    monkeypatch.setattr(enqueue, "queue", queue)
    await JIRA.connect("state", "code", 7)
    assert seen == ["connect", ("refresh", 7), JobKind.SYNC_JIRA]
