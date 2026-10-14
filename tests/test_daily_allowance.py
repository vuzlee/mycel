"""A person's chat stops being queued once 24 hours of spend, open jobs included, hit the cap."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.services import chat, enqueue
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
