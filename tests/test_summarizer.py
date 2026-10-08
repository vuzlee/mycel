"""The summarizer, and the prompt it is given."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

import mycel.agents.core.runner as runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.schemas import ProgressSummary
from mycel.agents.specialists.summarizer import Summarizer
from mycel.etl.normalize import JIRA
from mycel.infra.postgres.repositories.gold import WORKDAY_SECONDS, WorkItemRow
from mycel.infra.postgres.repositories.gold_stats import AssigneeLoad, DayEffort
from mycel.llm.budget import JobBudget
from mycel.services.analyze import render
from mycel.services.gather import ProgressWindow

pytestmark = pytest.mark.anyio

LOCAL = AgentSettings(model_spec="local:qwen3-4b")
PROJECT = "MYC"


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def _item(key: str = "MYC-7", **kw: Any) -> WorkItemRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": PROJECT,
        "issue_id": key.split("-")[-1],
        "issue_key": key,
        "kind": "story",
        "parent_key": "MYC-6",
        "title": "dựng dashboard",
        "status": "In Progress",
        "status_category": "doing",
        "sprint_id": None,
        "sprint_name": None,
        "sprint_state": None,
        "priority": "Medium",
        "assignee_account_id": "acct-1",
        "assignee_name": "Dev One",
        "original_estimate_seconds": 2 * WORKDAY_SECONDS,
        "time_spent_seconds": WORKDAY_SECONDS,
        "due_at": None,
        "created_at": _at(14),
        "resolved_at": None,
        "labels": [],
        "updated_at": _at(20),
    }
    return WorkItemRow(**{**fields, **kw})


def _window(items: list[WorkItemRow] | None = None, **kw: Any) -> ProgressWindow:
    rows = items if items is not None else [_item()]
    totals = {"todo": 0, "doing": 0, "done": 0}
    for row in rows:
        totals[row.status_category] += 1

    fields: dict[str, Any] = {
        "project": PROJECT,
        "since": _at(15, 0),
        "until": _at(21, 0),
        "items": rows,
        "by_epic": {"MYC-6": [r for r in rows if r.parent_key == "MYC-6"]},
        "epic_titles": {"MYC-6": "Pipeline and storage"},
        "totals": totals,
        "by_assignee": [
            AssigneeLoad(
                account_id="acct-1",
                name="Dev One",
                items=len(rows),
                done=totals["done"],
                estimated_seconds=2 * WORKDAY_SECONDS,
                spent_seconds=3 * WORKDAY_SECONDS,
            )
        ],
        "overdue": [],
        "effort_by_day": [DayEffort(day=date(2026, 9, 18), seconds=5 * 3600)],
    }
    return ProgressWindow(**{**fields, **kw})


def _good(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """A well-formed summary, for the tests that are about something else."""
    return ModelResponse(
        parts=[
            ToolCallPart(
                "final_result",
                {
                    "period": "15-21 September 2026",
                    "shipped": [],
                    "in_flight": [],
                    "at_risk": [],
                    "load": [],
                    "notes": [],
                },
            )
        ]
    )


@pytest.fixture
def deps() -> MycelDeps:
    return MycelDeps(job_id="job-1", budget=JobBudget("job-1", Decimal("1.00")), settings=LOCAL)


class TestThePrompt:
    """Everything the model can possibly know is in this string."""

    def test_it_carries_the_project_and_the_window(self) -> None:
        text = render(_window())
        assert "Project MYC, 2026-09-15 to 2026-09-21" in text

    def test_every_item_appears_with_its_key_and_status(self) -> None:
        """The key is how a reader finds the ticket, so a line without one is a dead end."""
        text = render(_window([_item("MYC-7"), _item("MYC-8", status="Done")]))
        assert "key=MYC-7" in text and "key=MYC-8" in text
        assert "status=In Progress" in text and "status=Done" in text

    def test_work_is_grouped_under_its_epic(self) -> None:
        """The level a plan is discussed at, resolved once rather than by the model."""
        text = render(_window())
        assert "MYC-6 — Pipeline and storage" in text

    def test_the_words_people_used_are_not_rewritten(self) -> None:
        """The model copies titles out of here."""
        assert "dựng dashboard" in render(_window())

    def test_seconds_become_days_for_the_reader(self) -> None:
        """Gold stores Jira's seconds; a person reads man-days, and this is the display."""
        text = render(_window())
        assert "estimated=2.0d" in text and "spent=1.0d" in text

    def test_the_kind_never_runs_into_the_title(self) -> None:
        """Named fields, because position is a thing a model has to count."""
        text = render(_window([_item("MYC-7", title="API skeleton")]))
        assert "kind=story  title=API skeleton" in text

    def test_an_overdue_item_is_called_out_separately(self) -> None:
        """The thing a stand-up exists to surface does not get buried in a list."""
        late = _item("MYC-9", due_at=_at(9))
        text = render(_window(overdue=[late]))
        assert "Past due and not done" in text and "MYC-9" in text

    def test_nothing_overdue_says_so_rather_than_trailing_off(self) -> None:
        """An empty heading reads as a truncated prompt, and a model fills in blanks."""
        assert "Nothing is past its due date." in render(_window())

    def test_the_load_line_states_the_gap(self) -> None:
        """Estimated against spent, subtracted here because arithmetic is not the model's job."""
        text = render(_window())
        assert "estimated 2.0d, spent 3.0d (1.0d over)" in text

    def test_effort_is_reported_per_day(self) -> None:
        """From worklogs, the one time series that survives a back-filled project."""
        assert "2026-09-18: 5.0h" in render(_window())

    def test_an_empty_window_says_it_is_empty(self) -> None:
        assert "Nothing moved in this window." in render(_window([]))

    def test_a_truncated_window_says_how_much_is_missing(self) -> None:
        """A summary that hides its own limit is worse than one that states it."""
        assert "37 older items were dropped" in render(_window(dropped=37))

    def test_a_whole_window_makes_no_such_claim(self) -> None:
        assert "dropped" not in render(_window())


class TestTheConfiguredLimit:
    """`tool_calls_limit: 0` in `config/agents/summarizer.yaml`."""

    @pytest.fixture
    def configured(self) -> AgentSettings:
        cfg = replace(AgentSettings.from_config(Summarizer.name), model_spec="local:qwen3-4b")
        assert cfg.tool_calls_limit == 0, "this test is about the zero"
        return cfg

    async def test_zero_still_allows_the_structured_output(self, configured: AgentSettings) -> None:
        deps = MycelDeps(
            job_id="job-1", budget=JobBudget("job-1", Decimal("1.00")), settings=configured
        )
        agent = Summarizer.build(configured)
        with agent.override(model=FunctionModel(_good)):
            result = await runner.run(agent, render(_window()), deps, configured)

        assert isinstance(result, ProgressSummary)

    async def test_zero_still_allows_a_reprompt(self, configured: AgentSettings) -> None:
        """A model that returns the wrong shape is asked again, as it is everywhere else."""
        calls: list[int] = []

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            if len(calls) == 1:
                return ModelResponse(
                    parts=[ToolCallPart("final_result", {"period": 5, "shipped": "nope"})]
                )
            return _good(messages, info)

        deps = MycelDeps(
            job_id="job-1", budget=JobBudget("job-1", Decimal("1.00")), settings=configured
        )
        agent = Summarizer.build(configured)
        with agent.override(model=FunctionModel(respond)):
            result = await runner.run(agent, render(_window()), deps, configured)

        assert len(calls) == 2
        assert isinstance(result, ProgressSummary)


class TestTheAgent:
    def test_it_has_no_tools(self) -> None:
        """The data is in the prompt."""
        assert Summarizer.toolsets() == []

    async def test_it_returns_a_structured_summary(self, deps: MycelDeps) -> None:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        {
                            "period": "15-21 September 2026",
                            "headline": "One shipped, one late.",
                            "health": "at_risk",
                            "shipped": [{"key": "MYC-7", "title": "Dashboard", "who": "Dev One"}],
                            "in_flight": [],
                            "at_risk": [
                                {
                                    "key": "MYC-9",
                                    "title": "Calendar",
                                    "who": "Dev One",
                                    "note": "four days past due",
                                }
                            ],
                            "load": [
                                {
                                    "person": "Dev One",
                                    "items": 2,
                                    "done": 1,
                                    "estimated": "2.0d",
                                    "spent": "3.0d",
                                }
                            ],
                            "notes": [],
                        },
                    )
                ]
            )

        agent = Summarizer.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            result = await agent.run(render(_window()), deps=deps)

        assert isinstance(result.output, ProgressSummary)
        late = result.output.at_risk[0]
        assert (late.key, late.note) == ("MYC-9", "four days past due")
        assert result.output.load[0].spent == "3.0d"
        assert result.output.headline == "One shipped, one late."
        assert result.output.health == "at_risk"

    async def test_a_row_carries_its_estimate_spent_and_due(self, deps: MycelDeps) -> None:
        """The three columns a standup argues about, and all three are copied."""

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        {
                            "period": "15-21 September 2026",
                            "shipped": [
                                {
                                    "key": "MYC-7",
                                    "title": "Dashboard",
                                    "estimated": "2.0d",
                                    "spent": "3.0d",
                                    "due": "2026-09-20",
                                },
                                {"key": "MYC-8", "title": "Schemas"},
                            ],
                        },
                    )
                ]
            )

        agent = Summarizer.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            result = await agent.run(render(_window()), deps=deps)

        first, second = result.output.shipped
        assert (first.estimated, first.spent, first.due) == ("2.0d", "3.0d", "2026-09-20")
        assert (second.estimated, second.spent, second.due) == ("", "", "")

    async def test_a_model_that_omits_the_verdict_still_parses(self, deps: MycelDeps) -> None:
        """`headline` and `health` carry defaults on purpose."""

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart("final_result", {"period": "15-21 September 2026"})]
            )

        agent = Summarizer.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            result = await agent.run(render(_window()), deps=deps)

        assert result.output.headline == ""
        assert result.output.health == "on_track"
