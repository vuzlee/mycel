"""The outbox: a job exists when its row commits, and reaches the broker even if a publish fails."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.repositories.outbox import OutboxRepository
from mycel.queue import context
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

    async def publish(job: Job, headers: dict[str, Any] | None = None) -> str:
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

        async def down(job: Job, headers: dict[str, Any] | None = None) -> str:
            raise ConnectionError("broker gone")

        monkeypatch.setattr(enqueue, "publish", down)
        job = await enqueue.stage(session, enqueue.ingest_job(1))
        await enqueue.send(job)
        await _age(session, 60)

        left = await OutboxRepository(session).unpublished(timedelta(0), 10)
        assert [body["job_id"] for body, _ in left] == [job.job_id]


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

        async def keep(job: Job, headers: dict[str, Any] | None = None) -> str:
            seen.append(job)
            return job.job_id

        monkeypatch.setattr(enqueue, "publish", keep)
        job = enqueue.chat_job(
            "q?",
            1,
            "",
            user_id=7,
            chips=["jira"],
            previous="",
            context="",
            model_ref="host:claude-sonnet-5",
        )
        await enqueue.stage(session, job)
        await _age(session, 60)

        await enqueue.relay()

        assert seen == [job]

    async def test_one_failed_publish_does_not_resend_the_ones_before_it(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A batch in one transaction rolled back the marks of rows already published."""
        _on(session, monkeypatch)
        sent: list[str] = []
        first = await enqueue.stage(session, enqueue.delete_job(1))
        second = await enqueue.stage(session, enqueue.delete_job(2))
        await _age(session, 60)

        async def second_fails(job: Job, headers: dict[str, Any] | None = None) -> str:
            if job.job_id == second.job_id:
                raise ConnectionError("broker gone")
            sent.append(job.job_id)
            return job.job_id

        monkeypatch.setattr(enqueue, "publish", second_fails)
        with pytest.raises(ConnectionError):
            await enqueue.relay()

        left = await OutboxRepository(session).unpublished(timedelta(0), 10)
        assert sent == [first.job_id]
        assert [body["job_id"] for body, _ in left] == [second.job_id]

    async def test_a_relayed_job_keeps_the_requests_trace(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without it the job's logs carry the scheduler's request id, not the asker's."""
        _on(session, monkeypatch)
        seen: list[dict[str, Any] | None] = []
        monkeypatch.setattr(context, "inject", lambda: {"x-request-id": "req-42"})
        await enqueue.stage(session, enqueue.delete_job(4))
        await _age(session, 60)

        async def keep(job: Job, headers: dict[str, Any] | None = None) -> str:
            seen.append(headers)
            return job.job_id

        monkeypatch.setattr(enqueue, "publish", keep)
        await enqueue.relay()

        assert seen == [{"x-request-id": "req-42"}]

    async def test_an_unreadable_row_does_not_block_the_rest(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        published = _on(session, monkeypatch)
        await OutboxRepository(session).add("old-kind", {"job_id": "old-kind", "kind": "gone"})
        job = await enqueue.stage(session, enqueue.delete_job(3))
        await _age(session, 60)

        await enqueue.relay()

        assert published == [job.job_id]


@needs_postgres
class TestTheRequestNeverRewindsATurn:
    async def test_a_finished_turn_stays_finished(self, session: AsyncSession) -> None:
        """The worker can finish before the request writes its `queued` row."""
        repo = AppRepository(session)
        user = await repo.create_user("race@example.com")
        thread = await repo.create_conversation(user.id, "chat", "q")
        await repo.upsert_turn(thread.id, "job-fast", "q", "done", answer="a")

        await repo.add_turn(thread.id, "job-fast", "q", status="queued")

        kept: Any = await repo.turn_by_job_id("job-fast")
        assert kept.status == "done" and kept.answer == "a"
