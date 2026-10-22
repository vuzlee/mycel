"""Connecting Jira queues its sync; a sync already running covers it."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

import mycel.domains.sync as sync
import mycel.plugins.jira.access as access
import mycel.services.enqueue as enqueue
import mycel.worker as worker
from mycel.plugins.jira import oauth as jira_oauth
from mycel.plugins.jira.plugin import PLUGIN as JIRA
from mycel.queue.job import Job, JobKind

pytestmark = pytest.mark.anyio


def _lock(free: bool):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def lock(name: str) -> AsyncIterator[bool]:
        assert name == "sync:jira"
        yield free

    return lock


async def test_the_worker_runs_a_sync_job(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    async def fake_sync() -> None:
        ran.append("sync")

    monkeypatch.setattr(sync, "try_lock", _lock(True))
    monkeypatch.setattr(JIRA, "sync", fake_sync)
    await worker.run(Job(kind=JobKind.SYNC, payload={"plugin": "jira"}))
    assert ran == ["sync"]


async def test_a_sync_already_running_covers_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_run() -> None:
        raise AssertionError("ran twice")

    monkeypatch.setattr(sync, "try_lock", _lock(False))
    monkeypatch.setattr(JIRA, "sync", must_not_run)
    await sync.run(Job(kind=JobKind.SYNC, payload={"plugin": "jira"}))


async def test_a_plugin_that_does_not_sync_is_never_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "try_lock", _lock(True))
    await sync.run(Job(kind=JobKind.SYNC, payload={"plugin": "google"}))
    await sync.run(Job(kind=JobKind.SYNC, payload={"plugin": "nope"}))


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
    assert seen == ["connect", ("refresh", 7), JobKind.SYNC]


def test_a_jira_hiccup_is_retried_not_parked() -> None:
    """A timeout or 5xx from Jira may pass in a minute; the SYNC job must be retried."""
    from mycel.plugins.errors import SourceError

    assert issubclass(SourceError, worker.TRANSIENT)


async def test_a_failed_follow_up_does_not_fail_the_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account is saved; a sync that could not be queued is the timer's job, not an error."""

    async def connect(*_: object) -> None: ...

    async def refresh(user_id: int) -> None: ...

    async def queue(job: Job) -> None:
        raise OSError("database went away")

    monkeypatch.setattr(jira_oauth, "connect", connect)
    monkeypatch.setattr(access, "refresh", refresh)
    monkeypatch.setattr(enqueue, "queue", queue)
    await JIRA.connect("state", "code", 7)
