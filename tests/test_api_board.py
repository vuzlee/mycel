"""The HTTP API: board."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mycel.api.app import create_app
from mycel.api.dependencies import current_user
from mycel.core.config import Settings
from mycel.infra.postgres.repositories.conversations import ConversationRow, TurnRow
from mycel.infra.postgres.repositories.gold import WorkItemRow
from mycel.infra.postgres.repositories.gold_stats import (
    AssigneeLoad,
    DayEffort,
    KindTally,
    SprintTally,
)
from mycel.infra.redis.results import JobResult
from mycel.services.auth import Principal
from mycel.services.conversations import ConversationSummary
from mycel.services.dashboard import Dashboard, EpicProgress

#: Who every request in this file is made by.
SIGNED_IN = Principal(id=1, email="tester@example.com")


def _signed_in(app: FastAPI) -> None:
    """Satisfy `Depends(current_user)` without a session table."""
    app.dependency_overrides[current_user] = lambda: SIGNED_IN


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An app with tracing off, so tests neither export spans nor need credentials."""
    app = create_app(Settings(otel_enabled=False))
    _signed_in(app)
    with TestClient(app, raise_server_exceptions=False) as running:
        yield running


def _queues(monkeypatch: pytest.MonkeyPatch, result: str | Exception) -> None:
    """Make the chat domain accept a job or fail, with no broker anywhere in sight."""

    async def fake_request(
        user_id: int, question: str, conversation_id: int | None = None, chips: Any = None
    ) -> tuple[str, int]:
        if isinstance(result, Exception):
            raise result
        return result, conversation_id or 1

    monkeypatch.setattr("mycel.api.routes.chat.request_chat", fake_request)


def _stored(
    monkeypatch: pytest.MonkeyPatch,
    result: JobResult | None,
    kept: TurnRow | None = None,
) -> None:
    """Make everything the route reads answer, with neither Redis nor Postgres here."""

    async def fake_fetch(job_id: str) -> JobResult | None:
        return result

    async def fake_find(job_id: str) -> TurnRow | None:
        return kept

    async def no_citations(job_id: str) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr("mycel.api.routes.chat.results.fetch", fake_fetch)
    monkeypatch.setattr("mycel.api.routes.chat.find_turn", fake_find)
    monkeypatch.setattr("mycel.api.routes.chat.citations.fetch", no_citations)


#: What a finished run left behind, for the tests that read a kept row.
KEPT_ANSWER = "Nothing was asked, so nothing happened."


def _kept(job_id: str, *, status: str = "done", age_s: float = 0.0) -> TurnRow:
    """A row as `app.turn` keeps it, for the fallback half of the result endpoint."""
    return TurnRow(
        id=1,
        conversation_id=1,
        job_id=job_id,
        question="what happened?",
        status=status,
        answer=KEPT_ANSWER if status == "done" else None,
        error=None,
        spent_usd=Decimal("0.0216"),
        steps=None,
        created_at=datetime.now(UTC) - timedelta(seconds=age_s),
    )


class _FakeSession:
    async def execute(self, statement: object) -> None:
        return None


def _database(monkeypatch: pytest.MonkeyPatch, up: bool) -> None:
    """Stand in for Postgres, so the API tests need no server."""

    @asynccontextmanager
    async def fake_scope() -> AsyncIterator[_FakeSession]:
        if not up:
            raise OSError("connection refused")
        yield _FakeSession()

    monkeypatch.setattr("mycel.api.health.session_scope", fake_scope)


def _may_read(monkeypatch: pytest.MonkeyPatch, projects: set[str]) -> None:
    """What `services/permission.py` reads, without a database: this person's projects."""

    async def fake(user: Principal) -> frozenset[str]:
        return frozenset(projects)

    monkeypatch.setattr("mycel.services.permission.readable_projects", fake)


def _no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A session that is never used, for a domain whose service is stubbed."""

    @asynccontextmanager
    async def fake() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr("mycel.services.dashboards.session_scope", fake)


class TestTheBoard:
    """`GET /dashboard/{project}`: counting queries, answered inside the request."""

    def _answers(self, monkeypatch: pytest.MonkeyPatch, board: Dashboard) -> None:
        async def fake_build(session: Any, project: str, since: Any, until: Any) -> Dashboard:
            return board

        _may_read(monkeypatch, {"MYC"})
        _no_session(monkeypatch)
        monkeypatch.setattr("mycel.services.dashboards.build_dashboard", fake_build)

    def _late(self) -> WorkItemRow:
        """One story, past its due date and still in progress — the row the screen is for."""
        return WorkItemRow(
            source="jira",
            project="MYC",
            issue_id="7",
            issue_key="MYC-7",
            kind="story",
            parent_key="MYC-6",
            title="dựng dashboard",
            status="In Progress",
            status_category="doing",
            priority="Highest",
            sprint_id=2,
            sprint_name="Sprint 0",
            sprint_state="active",
            assignee_account_id="acct-1",
            assignee_name="Dev One",
            original_estimate_seconds=2 * 8 * 3600,
            time_spent_seconds=3 * 8 * 3600,
            due_at=datetime(2026, 9, 16, tzinfo=UTC),
            created_at=datetime(2026, 9, 14, tzinfo=UTC),
            resolved_at=None,
            labels=[],
            updated_at=datetime(2026, 9, 20, tzinfo=UTC),
        )

    def _board(self, **kw: object) -> Dashboard:
        until = datetime(2026, 9, 21, tzinfo=UTC)
        fields: dict[str, object] = {
            "project": "MYC",
            "since": until - timedelta(days=7),
            "until": until,
            "totals": {"todo": 1, "doing": 1, "done": 2},
            "all_totals": {"todo": 2, "doing": 1, "done": 5},
            "priorities": {"Highest": 1, "High": 0, "Medium": 2, "Low": 0, "Lowest": 0},
            "kinds": [KindTally(kind="story", items=5, done=3)],
            "recent": [self._late()],
            "overdue": [self._late()],
            "assignees": [
                AssigneeLoad(
                    account_id="acct-1",
                    name="Dev One",
                    items=3,
                    done=2,
                    estimated_seconds=2 * 8 * 3600,
                    spent_seconds=3 * 8 * 3600,
                )
            ],
            "epics": [
                EpicProgress(
                    issue_key="MYC-6",
                    title="Pipeline and storage",
                    status_category="doing",
                    items=4,
                    done=3,
                    moved=3,
                    moved_done=2,
                )
            ],
            "sprints": [SprintTally(sprint_id=2, name="Sprint 0", state="active", items=6, done=4)],
            "effort_by_day": [DayEffort(day=date(2026, 9, 18), seconds=5 * 3600)],
            "calendar": [DayEffort(day=date(2026, 9, 18), seconds=5 * 3600)],
        }
        return Dashboard(**{**fields, **kw})  # type: ignore[arg-type]

    def test_the_numbers_come_back(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._answers(monkeypatch, self._board())
        body = client.get("/dashboard/MYC").json()

        assert body["totals"] == {"todo": 1, "doing": 1, "done": 2}
        assert body["assignees"][0]["name"] == "Dev One"
        assert body["epics"][0]["issue_key"] == "MYC-6"

    def test_a_late_ticket_is_visible_without_hunting(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Overdue is its own list, not a flag somebody has to go looking for."""
        self._answers(monkeypatch, self._board())
        body = client.get("/dashboard/MYC").json()

        assert [item["issue_key"] for item in body["overdue"]] == ["MYC-7"]
        assert body["overdue"][0]["title"] == "dựng dashboard"

    def test_the_gap_is_reported_in_seconds(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spent minus estimated, and gold's own unit. Days are the page's decision."""
        self._answers(monkeypatch, self._board())
        body = client.get("/dashboard/MYC").json()

        assert body["assignees"][0]["gap_seconds"] == 8 * 3600

    def test_effort_is_a_curve_over_days(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """From worklogs, so a back-filled project still has an honest time series."""
        self._answers(monkeypatch, self._board())
        body = client.get("/dashboard/MYC").json()

        assert body["effort_by_day"] == [{"day": "2026-09-18", "seconds": 5 * 3600}]

    def test_priority_kind_and_activity_reach_the_page(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Priority, kind and the feed."""
        self._answers(monkeypatch, self._board())
        body = client.get("/dashboard/MYC").json()

        assert body["priorities"]["Highest"] == 1
        assert body["kinds"] == [{"kind": "story", "items": 5, "done": 3}]
        assert body["recent"][0]["updated_at"].startswith("2026-09-20")
        assert body["recent"][0]["priority"] == "Highest"

    def test_a_project_with_no_data_is_empty_not_missing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A project set up but not yet synced is a normal state, not a 404."""
        self._answers(
            monkeypatch,
            self._board(
                totals={"todo": 0, "doing": 0, "done": 0},
                priorities={},
                kinds=[],
                recent=[],
                overdue=[],
                assignees=[],
                epics=[],
                effort_by_day=[],
            ),
        )
        response = client.get("/dashboard/MYC")

        assert response.status_code == 200
        assert response.json()["assignees"] == []

    def test_the_window_is_a_parameter(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, int] = {}

        async def fake_build(session: Any, project: str, since: Any, until: Any) -> Dashboard:
            seen["days"] = round((until - since).total_seconds() / 86400)
            return self._board()

        _may_read(monkeypatch, {"MYC"})
        _no_session(monkeypatch)
        monkeypatch.setattr("mycel.services.dashboards.build_dashboard", fake_build)
        client.get("/dashboard/MYC?days=30")
        assert seen["days"] == 30

    def test_an_absurd_window_is_refused(self, client: TestClient) -> None:
        """A year on one screen is an export, not a dashboard."""
        assert client.get("/dashboard/MYC?days=4000").status_code == 422

    def test_someone_elses_project_is_refused_before_it_is_read(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Permission is checked first, so a 403 costs no query."""
        read: list[str] = []

        async def fake_build(session: Any, project: str, since: Any, until: Any) -> Dashboard:
            read.append(project)
            return self._board()

        _may_read(monkeypatch, set())
        _no_session(monkeypatch)
        monkeypatch.setattr("mycel.services.dashboards.build_dashboard", fake_build)

        assert client.get("/dashboard/MYC").status_code == 403
        assert read == []


class TestTheLists:
    """The two lists a page reads before it can ask for anything else."""

    def test_projects_are_filtered_by_permission(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The route lists what this person may read, not what the deployment has."""

        async def fake_list(session: Any) -> list[str]:
            return ["MYC", "OPS"]

        _may_read(monkeypatch, {"MYC"})
        _no_session(monkeypatch)
        monkeypatch.setattr("mycel.services.dashboards.list_projects", fake_list)

        assert client.get("/projects").json() == ["MYC"]

    def test_threads_are_this_person_s(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whose sidebar it is comes from the session, never from the query string."""
        asked: list[int] = []

        async def fake_conversations(user_id: int, limit: int = 50) -> list[ConversationSummary]:
            asked.append(user_id)
            return [
                ConversationSummary(
                    conversation=ConversationRow(
                        id=7,
                        user_id=user_id,
                        title="what happened?",
                        kind="chat",
                        created_at=datetime.now(UTC),
                    ),
                    job_id="job-abc",
                    status="done",
                )
            ]

        monkeypatch.setattr("mycel.services.conversations.list_conversations", fake_conversations)
        body = client.get("/conversations").json()

        assert asked == [SIGNED_IN.id]
        assert body[0]["job_id"] == "job-abc"

    def test_a_thread_nobody_ran_still_shows(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A queued run the worker never picked up is the row someone most needs to see."""

        async def fake_conversations(user_id: int, limit: int = 50) -> list[ConversationSummary]:
            return [
                ConversationSummary(
                    conversation=ConversationRow(
                        id=8,
                        user_id=user_id,
                        title="never started",
                        kind="chat",
                        created_at=datetime.now(UTC),
                    ),
                    job_id=None,
                    status=None,
                )
            ]

        monkeypatch.setattr("mycel.services.conversations.list_conversations", fake_conversations)
        body = client.get("/conversations").json()

        assert len(body) == 1 and body[0]["job_id"] is None

    def test_forgetting_a_thread_scopes_itself_to_the_caller(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The signed-in id goes to the domain, not one the caller could name."""
        seen: list[tuple[int, int]] = []

        async def fake_forget(user_id: int, conversation_id: int) -> bool:
            seen.append((user_id, conversation_id))
            return True

        monkeypatch.setattr("mycel.services.conversations.forget_conversation", fake_forget)
        response = client.delete("/conversations/7")

        assert response.status_code == 204
        assert seen == [(SIGNED_IN.id, 7)]

    def test_someone_elses_thread_is_a_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not 403: the difference is the one thing someone probing ids would learn."""

        async def fake_forget(user_id: int, conversation_id: int) -> bool:
            return False

        monkeypatch.setattr("mycel.services.conversations.forget_conversation", fake_forget)

        assert client.delete("/conversations/7").status_code == 404

    def test_pinning_scopes_itself_to_the_caller(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[tuple[int, int, bool]] = []

        async def fake_pin(user_id: int, conversation_id: int, pinned: bool) -> bool:
            seen.append((user_id, conversation_id, pinned))
            return conversation_id == 7

        monkeypatch.setattr("mycel.services.conversations.pin_conversation", fake_pin)

        assert client.put("/conversations/7/pin", json={"pinned": True}).status_code == 204
        assert client.put("/conversations/8/pin", json={"pinned": True}).status_code == 404
        assert seen[0] == (SIGNED_IN.id, 7, True)
