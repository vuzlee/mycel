"""The outbox: a job exists when its row commits, and reaches the broker even if a publish fails."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.repositories.outbox import OutboxRepository
from mycel.queue.job import Job
from mycel.services import enqueue
from tests.fakes import needs_postgres
from tests.pg import AppRepository

pytestmark = pytest.mark.anyio


def _on(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run `enqueue` on the test's session and capture what it publishes."""
    published: list[str] = []

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        yield session
        await session.flush()

    async def publish(job: Job) -> str:
        published.append(job.job_id)
        return job.job_id

    monkeypatch.setattr(enqueue, "session_scope", scope)
    monkeypatch.setattr(enqueue, "publish", publish)
    return published


async def _age(session: AsyncSession, seconds: int) -> None:
    await session.execute(
        text(f"UPDATE app.outbox SET created_at = now() - interval '{seconds} seconds'")
    )


@needs_postgres
class TestSend:
    async def test_a_published_job_is_marked(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        published = _on(session, monkeypatch)
        job = await enqueue.stage(session, enqueue.ingest_job(1))
        await enqueue.send(job)
        await _age(session, 60)

        assert published == [job.job_id]
        assert await OutboxRepository(session).unpublished(timedelta(0), 10) == []

    async def test_a_failed_publish_is_left_for_the_relay(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The request already committed; it must not fail, and the job must not be lost."""
        _on(session, monkeypatch)

        async def down(job: Job) -> str:
            raise ConnectionError("broker gone")

        monkeypatch.setattr(enqueue, "publish", down)
        job = await enqueue.stage(session, enqueue.ingest_job(1))
        await enqueue.send(job)
        await _age(session, 60)

        left = await OutboxRepository(session).unpublished(timedelta(0), 10)
        assert [body["job_id"] for body in left] == [job.job_id]


@needs_postgres
class TestRelay:
    async def test_it_publishes_what_the_request_could_not(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        published = _on(session, monkeypatch)
        job = await enqueue.stage(session, enqueue.delete_job(3))
        await _age(session, 60)

        await enqueue.relay()

        assert published == [job.job_id]
        assert await OutboxRepository(session).unpublished(timedelta(0), 10) == []

    async def test_it_leaves_a_fresh_row_to_the_request(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise every job is published twice: once by the request, once here."""
        published = _on(session, monkeypatch)
        await enqueue.stage(session, enqueue.ingest_job(1))

        await enqueue.relay()

        assert published == []

    async def test_the_job_comes_back_whole(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Job] = []
        _on(session, monkeypatch)

        async def keep(job: Job) -> str:
            seen.append(job)
            return job.job_id

        monkeypatch.setattr(enqueue, "publish", keep)
        job = enqueue.chat_job("q?", 1, "", user_id=7, chips=["jira"], previous="", context="")
        await enqueue.stage(session, job)
        await _age(session, 60)

        await enqueue.relay()

        assert seen == [job]


@needs_postgres
class TestTheRequestNeverRewindsATurn:
    async def test_a_finished_turn_stays_finished(self, session: AsyncSession) -> None:
        """The worker can finish before the request writes its `queued` row."""
        repo = AppRepository(session)
        user = await repo.create_user("race@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "q")
        await repo.upsert_turn(thread.id, "job-fast", "q", "done", answer="a")

        await repo.add_turn(thread.id, "job-fast", "q", status="queued")

        kept: Any = await repo.turn_by_job_id("job-fast")
        assert kept.status == "done" and kept.answer == "a"
