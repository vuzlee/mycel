"""A person's chat stops being queued once 24 hours of spend, open jobs included, hit the cap."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.infra.postgres.models import Turn
from mycel.queue.job import Job
from mycel.services import chat, enqueue, models
from tests.fakes import needs_postgres
from tests.pg import AppRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def on_session(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        yield session
        await session.flush()

    async def sent(job: object) -> None:
        pass

    monkeypatch.setattr(chat, "session_scope", scope)
    monkeypatch.setattr(enqueue, "session_scope", scope)
    monkeypatch.setattr(enqueue, "send", sent)
    monkeypatch.setenv("USER_DAILY_USD", "1.00")
    monkeypatch.setenv("JOB_CEILING_USD", "0.50")
    get_settings.cache_clear()


@needs_postgres
class TestDailyAllowance:
    async def test_spend_already_made_counts(self, session: AsyncSession, on_session: None) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("spent@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "q")
        await repo.upsert_turn(thread.id, "job-a", "q", "done", spent_usd=Decimal("0.60"))

        await chat.request_chat(user.id, "one more?")

        with pytest.raises(chat.DailyLimitReached):
            await chat.request_chat(user.id, "and another?")

    async def test_open_jobs_count_at_their_ceiling(
        self, session: AsyncSession, on_session: None
    ) -> None:
        """Twenty questions queued in a second would each spend before any was counted."""
        user = await AppRepository(session).create_user("burst@example.com", "x")

        await chat.request_chat(user.id, "first")
        await chat.request_chat(user.id, "second")

        with pytest.raises(chat.DailyLimitReached):
            await chat.request_chat(user.id, "third")

    async def test_someone_else_s_spend_is_theirs(
        self, session: AsyncSession, on_session: None
    ) -> None:
        repo = AppRepository(session)
        big = await repo.create_user("big@example.com", "x")
        small = await repo.create_user("small@example.com", "x")
        thread = await repo.create_conversation(big.id, "chat", "q")
        await repo.upsert_turn(thread.id, "job-b", "q", "done", spent_usd=Decimal("5"))

        await chat.request_chat(small.id, "mine is fine")


@needs_postgres
class TestOneTurnAtATime:
    async def test_a_second_question_waits_for_the_first(
        self, session: AsyncSession, on_session: None
    ) -> None:
        user = await AppRepository(session).create_user("twice@example.com", "x")
        _, thread = await chat.request_chat(user.id, "first")

        with pytest.raises(chat.TurnInProgress):
            await chat.request_chat(user.id, "second", thread)

    async def test_an_answered_turn_frees_the_conversation(
        self, session: AsyncSession, on_session: None
    ) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("after@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "q")
        await repo.upsert_turn(thread.id, "job-c", "q", "done", spent_usd=Decimal("0.01"))

        await chat.request_chat(user.id, "next", thread.id)


@needs_postgres
class TestPickedModel:
    async def test_the_ref_rides_on_the_turn_and_the_job(
        self, session: AsyncSession, on_session: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[Job] = []

        async def keep(job: Job) -> None:
            sent.append(job)

        monkeypatch.setattr(enqueue, "send", keep)
        user = await AppRepository(session).create_user("picks@example.com", "x")

        _, thread = await chat.request_chat(user.id, "q?", model_ref="host:claude-sonnet-5")

        turns = await AppRepository(session).turns_for_conversation(thread)
        stored = await session.scalar(select(Turn.model_ref).where(Turn.conversation_id == thread))
        assert stored == "host:claude-sonnet-5"
        assert sent[0].payload["model_ref"] == "host:claude-sonnet-5"
        assert "api_key" not in sent[0].payload
        assert len(turns) == 1

    async def test_a_model_that_is_off_is_refused_before_queueing(
        self, session: AsyncSession, on_session: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def refuse(user_id: int, ref: str | None) -> str:
            raise models.UnknownModel(ref)

        monkeypatch.setattr(models, "usable", refuse)
        user = await AppRepository(session).create_user("off@example.com", "x")

        with pytest.raises(models.UnknownModel):
            await chat.request_chat(user.id, "q?", model_ref="host:off")
        assert await session.scalar(select(func.count()).select_from(Turn)) == 0
