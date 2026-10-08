"""Postgres: app."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fakes import needs_postgres
from tests.pg import (
    AppRepository,
)

pytestmark = pytest.mark.anyio


@needs_postgres
class TestATurnKeepsItsToolCalls:
    """`app.turn.steps`, so a thread reopened after the stream expired is not an empty middle."""

    async def test_the_steps_come_back_as_they_were_written(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("steps@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "what happened?")
        steps = [{"seq": 1, "agent": "analyst", "type": "tool_called", "payload": {"t": "sql"}}]

        await repo.upsert_turn(thread.id, "job-1", "q", "done", answer="a", steps=steps)

        kept = await repo.turn_by_job_id("job-1")
        assert kept is not None and kept.steps == steps

    async def test_a_later_write_without_steps_does_not_erase_them(
        self, session: AsyncSession
    ) -> None:
        """A redelivery that ends in failure must not wipe what a successful attempt already
        recorded.
        """
        repo = AppRepository(session)
        user = await repo.create_user("redeliver@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "what happened?")
        steps = [{"seq": 1, "agent": "analyst", "type": "tool_called", "payload": {}}]

        await repo.upsert_turn(thread.id, "job-2", "q", "done", answer="a", steps=steps)
        await repo.upsert_turn(thread.id, "job-2", "q", "failed", error="boom")

        kept = await repo.turn_by_job_id("job-2")
        assert kept is not None and kept.status == "failed" and kept.steps == steps


@needs_postgres
class TestForgettingAThread:
    """Delete is the one write in `app` that has to be scoped by hand."""

    async def test_the_runs_under_it_go_too(self, session: AsyncSession) -> None:
        """`ON DELETE CASCADE` on `turn.conversation_id`, proved rather than assumed."""
        repo = AppRepository(session)
        user = await repo.create_user("keep@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "what happened?")
        await repo.upsert_turn(thread.id, "job-1", "q", "done")

        assert await repo.delete_conversation(thread.id, user.id) is True
        assert await repo.turn_by_job_id("job-1") is None

    async def test_someone_elses_thread_is_left_alone(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        mine = await repo.create_user("mine@example.com", "x")
        theirs = await repo.create_user("theirs@example.com", "x")
        thread = await repo.create_conversation(theirs.id, "chat", "not yours")

        assert await repo.delete_conversation(thread.id, mine.id) is False
        assert await repo.conversation_by_id(thread.id) is not None


@needs_postgres
class TestTheSidebarFollowsTheLastThingSaid:
    """Order by the newest turn, not by when the thread was opened."""

    async def _stamp(self, session: AsyncSession, table: str, key: str, month: int) -> None:
        # A turn carries both times, and the order reads the later one.
        columns = "created_at = :when"
        if table == "turn":
            columns += ", updated_at = :when"
        await session.execute(
            text(f"UPDATE app.{table} SET {columns} WHERE {key}"),
            {"when": datetime(2026, month, 1, tzinfo=UTC)},
        )

    async def test_a_finished_run_lifts_its_thread(self, session: AsyncSession) -> None:
        """The second write of a turn moves the thread."""
        repo = AppRepository(session)
        user = await repo.create_user("finished@example.com", "x")
        early = await repo.create_conversation(user.id, "chat", "asked first")
        later = await repo.create_conversation(user.id, "chat", "asked second")
        await repo.upsert_turn(early.id, "job-early", "q", "queued")
        await repo.upsert_turn(later.id, "job-later", "q", "queued")
        await session.flush()

        await self._stamp(session, "conversation", f"id = {early.id}", 1)
        await self._stamp(session, "conversation", f"id = {later.id}", 2)
        await self._stamp(session, "turn", "job_id = 'job-early'", 1)
        await self._stamp(session, "turn", "job_id = 'job-later'", 2)

        # The older thread finishes last, which is the whole point.
        await repo.upsert_turn(early.id, "job-early", "q", "done", answer="here")
        await session.flush()

        rows = await repo.conversations_for(user.id)
        assert [row.id for row in rows] == [early.id, later.id]

    async def test_a_reopened_thread_comes_back_to_the_top(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("sidebar@example.com", "x")
        old = await repo.create_conversation(user.id, "chat", "opened first")
        new = await repo.create_conversation(user.id, "chat", "opened second")
        await repo.upsert_turn(old.id, "job-old", "q", "done")
        await session.flush()

        await self._stamp(session, "conversation", f"id = {old.id}", 1)
        await self._stamp(session, "conversation", f"id = {new.id}", 2)
        await self._stamp(session, "turn", "job_id = 'job-old'", 3)

        rows = await repo.conversations_for(user.id)
        assert [row.id for row in rows] == [old.id, new.id]

    async def test_a_pinned_thread_stays_on_top(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("pin@example.com", "x")
        old = await repo.create_conversation(user.id, "chat", "pinned")
        new = await repo.create_conversation(user.id, "chat", "newer")
        await session.flush()
        await self._stamp(session, "conversation", f"id = {old.id}", 1)
        await self._stamp(session, "conversation", f"id = {new.id}", 2)

        assert await repo.pin_conversation(old.id, user.id, True) is True
        rows = await repo.conversations_for(user.id)
        assert [row.id for row in rows] == [old.id, new.id]
        assert rows[0].pinned_at is not None

        await repo.pin_conversation(old.id, user.id, False)
        rows = await repo.conversations_for(user.id)
        assert [row.id for row in rows] == [new.id, old.id]

    async def test_someone_elses_thread_cannot_be_pinned(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        mine = await repo.create_user("pin-mine@example.com", "x")
        theirs = await repo.create_user("pin-theirs@example.com", "x")
        thread = await repo.create_conversation(theirs.id, "chat", "not yours")

        assert await repo.pin_conversation(thread.id, mine.id, True) is False

    async def test_a_thread_with_no_turns_still_sorts(self, session: AsyncSession) -> None:
        """`COALESCE` back to its own `created_at`."""
        repo = AppRepository(session)
        user = await repo.create_user("empty@example.com", "x")
        spoken = await repo.create_conversation(user.id, "chat", "answered")
        silent = await repo.create_conversation(user.id, "chat", "never answered")
        await repo.upsert_turn(spoken.id, "job-spoken", "q", "done")
        await session.flush()

        await self._stamp(session, "conversation", f"id = {spoken.id}", 1)
        await self._stamp(session, "conversation", f"id = {silent.id}", 3)
        await self._stamp(session, "turn", "job_id = 'job-spoken'", 2)

        rows = await repo.conversations_for(user.id)
        assert [row.id for row in rows] == [silent.id, spoken.id]


@needs_postgres
class TestAConnectedGoogleAccount:
    """One row per person, and reconnecting replaces it rather than adding a second."""

    async def test_connecting_keeps_what_the_calendar_needs(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("cal@example.com", "x")

        await repo.upsert_google_account(user.id, "cal@gmail.com", "sealed-token", "openid email")

        row = await repo.google_account(user.id)
        assert row is not None
        assert row.email == "cal@gmail.com"
        assert row.refresh_token_encrypted == "sealed-token"
        assert row.scope == "openid email"

    async def test_reconnecting_replaces_the_token(self, session: AsyncSession) -> None:
        """A second consent round supersedes the first."""
        repo = AppRepository(session)
        user = await repo.create_user("again@example.com", "x")

        await repo.upsert_google_account(user.id, "a@gmail.com", "first", "openid")
        await repo.upsert_google_account(user.id, "b@gmail.com", "second", "openid email")

        row = await repo.google_account(user.id)
        assert row is not None
        assert row.refresh_token_encrypted == "second"
        assert row.email == "b@gmail.com"

    async def test_nobody_connected_is_no_row(self, session: AsyncSession) -> None:
        """The normal state, and it must read as `None` rather than as an error."""
        repo = AppRepository(session)
        user = await repo.create_user("none@example.com", "x")

        assert await repo.google_account(user.id) is None

    async def test_disconnecting_removes_it(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("gone@example.com", "x")
        await repo.upsert_google_account(user.id, "g@gmail.com", "token", "openid")

        assert await repo.delete_google_account(user.id) is True
        assert await repo.google_account(user.id) is None

    async def test_disconnecting_twice_is_not_an_error(self, session: AsyncSession) -> None:
        """The end state is what was asked for, which is all a disconnect promises."""
        repo = AppRepository(session)
        user = await repo.create_user("twice@example.com", "x")

        assert await repo.delete_google_account(user.id) is False

    async def test_one_persons_account_is_not_anothers(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        mine = await repo.create_user("mine@example.com", "x")
        theirs = await repo.create_user("theirs@example.com", "x")
        await repo.upsert_google_account(mine.id, "m@gmail.com", "token", "openid")

        assert await repo.google_account(theirs.id) is None


@needs_postgres
class TestAConnectedJiraAccount:
    """The Google table's twin."""

    async def _connect(
        self, repo: AppRepository, email: str, *, account: str = "acct-1", token: str = "sealed"
    ) -> int:
        user = await repo.create_user(email, "x")
        await repo.upsert_jira_account(
            user.id, account, "Nam Nguyen", "cloud-1", token, "read:jira-work"
        )
        return user.id

    async def test_connecting_keeps_what_a_write_needs(self, session: AsyncSession) -> None:
        """The account id is the author of every write, and the cloud id addresses the site."""
        repo = AppRepository(session)
        user_id = await self._connect(repo, "jira@example.com")

        row = await repo.jira_account(user_id)
        assert row is not None
        assert (row.account_id, row.cloud_id) == ("acct-1", "cloud-1")
        assert row.display_name == "Nam Nguyen"
        assert row.refresh_token_encrypted == "sealed"

    async def test_reconnecting_replaces_the_token(self, session: AsyncSession) -> None:
        """A dead token sitting beside a live one is two answers to "whose grant"."""
        repo = AppRepository(session)
        user = await repo.create_user("again@example.com", "x")
        await repo.upsert_jira_account(
            user.id, "acct-1", "Nam", "cloud-1", "first", "read:jira-work"
        )
        await repo.upsert_jira_account(
            user.id, "acct-1", "Nam Nguyen", "cloud-1", "second", "read:jira-work"
        )

        row = await repo.jira_account(user.id)
        assert row is not None
        assert row.refresh_token_encrypted == "second"
        assert row.display_name == "Nam Nguyen"

    async def test_everyone_connected_is_listed_for_the_refresh(
        self, session: AsyncSession
    ) -> None:
        repo = AppRepository(session)
        first = await self._connect(repo, "one@example.com")
        second = await self._connect(repo, "two@example.com", account="acct-2")

        assert set(await repo.jira_connected_users()) >= {first, second}

    async def test_disconnecting_takes_the_access_with_it(self, session: AsyncSession) -> None:
        """The access came from Jira on this token; with no token nothing keeps it true."""
        repo = AppRepository(session)
        user_id = await self._connect(repo, "leaving@example.com")
        await repo.replace_projects(user_id, ["MYC"])

        assert await repo.delete_jira_account(user_id) is True
        assert await repo.projects_for(user_id) == frozenset()

    async def test_a_rotated_refresh_token_replaces_the_spent_one(
        self, session: AsyncSession
    ) -> None:
        """Atlassian retires a refresh token once it is spent."""
        repo = AppRepository(session)
        user_id = await self._connect(repo, "rotate@example.com", token="old")

        locked = await repo.jira_account_locked(user_id)
        assert locked is not None
        await repo.set_jira_refresh_token(user_id, "new")

        row = await repo.jira_account(user_id)
        assert row is not None
        assert row.refresh_token_encrypted == "new"

    async def test_disconnecting_twice_is_not_an_error(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("twice-jira@example.com", "x")

        assert await repo.delete_jira_account(user.id) is False


@needs_postgres
class TestTheSyncRecord:
    """The sync belongs to no person, so its record is one row of its own."""

    async def test_before_any_run_there_is_nothing(self, session: AsyncSession) -> None:
        state = await AppRepository(session).sync_state()
        assert (state.last_success_at, state.last_error) == (None, None)

    async def test_a_failure_keeps_the_last_success(self, session: AsyncSession) -> None:
        """A stopped sync must not erase when it last worked — that is what dates it."""
        repo = AppRepository(session)
        ok = datetime(2026, 10, 6, 9, tzinfo=UTC)
        await repo.record_sync(ok)
        await repo.record_sync(datetime(2026, 10, 6, 10, tzinfo=UTC), "401 from Jira")

        state = await repo.sync_state()
        assert state.last_success_at == ok
        assert state.last_error == "401 from Jira"

    async def test_a_success_clears_the_error(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        await repo.record_sync(datetime(2026, 10, 6, 10, tzinfo=UTC), "401 from Jira")
        await repo.record_sync(datetime(2026, 10, 6, 11, tzinfo=UTC))

        assert (await repo.sync_state()).last_error is None
