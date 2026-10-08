"""Postgres: dashboard."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.services.dashboard import RECENT_LIMIT, build_dashboard
from mycel.services.gather import gather_progress
from tests.fakes import needs_postgres
from tests.pg import (
    PROJECT,
    GoldRepository,
    _at,
    _epic,
    _item,
    _worklog,
)

pytestmark = pytest.mark.anyio


@needs_postgres
class TestTheProgressWindow:
    """What the summarizer is given, assembled from gold in one place."""

    async def test_it_carries_the_items_and_the_totals(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items(
            [_item("MYC-7"), _item("MYC-8", status_category="done")]
        )

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert len(window.items) == 2
        assert window.totals == {"todo": 0, "doing": 1, "done": 1}

    async def test_work_is_grouped_under_its_epic(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items([_epic(), _item()])

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert [c.issue_key for c in window.by_epic["MYC-6"]] == ["MYC-7"]
        assert window.epic_titles["MYC-6"] == "Pipeline and storage"

    async def test_work_with_no_epic_is_not_lost(self, session: AsyncSession) -> None:
        """A standalone task is ordinary work, not a data error."""
        await GoldRepository(session).upsert_items([_item("MYC-9", parent_key=None)])

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert [o.issue_key for o in window.orphans] == ["MYC-9"]

    async def test_an_empty_window_is_not_an_error(self, session: AsyncSession) -> None:
        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert window.is_empty and window.dropped == 0

    async def test_too_many_items_drops_the_oldest_and_counts_them(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The newest items survive the cut."""
        monkeypatch.setattr("mycel.services.gather.MAX_ITEMS", 2)
        await GoldRepository(session).upsert_items(
            [_item(f"MYC-{n}", updated_at=_at(15) + timedelta(hours=n)) for n in (1, 2, 3)]
        )

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert window.dropped == 1
        assert [i.issue_key for i in window.items] == ["MYC-2", "MYC-3"]


@needs_postgres
class TestTheDashboard:
    """The same window the summarizer reads, shaped for a screen."""

    async def test_it_counts_by_category(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items(
            [_item("MYC-7"), _item("MYC-8", status_category="done")]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 1, "done": 1}

    async def test_an_epic_carries_how_far_its_children_got(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items(
            [_epic(), _item("MYC-7"), _item("MYC-8", status_category="done")]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [(e.issue_key, e.items, e.done, e.percent) for e in board.epics] == [
            ("MYC-6", 2, 1, 50)
        ]

    async def test_an_epic_is_sized_by_all_its_children_not_the_window(
        self, session: AsyncSession
    ) -> None:
        """The bar is the epic; `moved` is the week."""
        await GoldRepository(session).upsert_items(
            [
                _epic(),
                _item("MYC-7", status_category="done", updated_at=_at(2)),
                _item("MYC-8", status_category="done"),
                _item("MYC-9"),
                _item("MYC-10"),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        epic = board.epics[0]
        assert (epic.items, epic.done, epic.percent) == (4, 2, 50)
        assert (epic.moved, epic.moved_done) == (3, 1)

    async def test_an_epic_nobody_has_touched_is_still_a_row(self, session: AsyncSession) -> None:
        """A plan that hides its untouched parts is a plan that looks shorter than it is."""
        await GoldRepository(session).upsert_items([_epic(), _item("MYC-7")])

        board = await build_dashboard(session, PROJECT, _at(20), _at(21))
        assert [(e.issue_key, e.moved, e.percent) for e in board.epics] == [("MYC-6", 0, 0)]

    async def test_progress_is_the_project_not_the_window(self, session: AsyncSession) -> None:
        """`percent` answers "how far are we", which a window cannot answer."""
        await GoldRepository(session).upsert_items(
            [
                _item("MYC-7", status_category="done"),
                _item("MYC-8", updated_at=_at(2)),
                _item("MYC-9", updated_at=_at(2)),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 0, "done": 1}
        assert board.all_totals == {"todo": 0, "doing": 2, "done": 1}
        assert board.percent == 33

    async def test_a_late_ticket_is_on_the_board_not_behind_a_count(
        self, session: AsyncSession
    ) -> None:
        await GoldRepository(session).upsert_items([_item(due_at=_at(10))])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [r.issue_key for r in board.overdue] == ["MYC-7"]

    async def test_an_old_overdue_ticket_is_late_without_being_in_the_window(
        self, session: AsyncSession
    ) -> None:
        """The one asymmetry the dashboard's captions promise, pinned."""
        await GoldRepository(session).upsert_items([_item(due_at=_at(10), updated_at=_at(11))])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [r.issue_key for r in board.overdue] == ["MYC-7"]
        assert board.totals == {"todo": 0, "doing": 0, "done": 0}

    async def test_spent_is_the_ticket_lifetime_and_effort_is_the_window(
        self, session: AsyncSession
    ) -> None:
        """Two numbers on one screen that are allowed to disagree, pinned so they stay so."""
        gold = GoldRepository(session)
        await gold.upsert_items([_item("MYC-7", time_spent_seconds=10 * 3600)])
        await gold.upsert_worklogs(
            [_worklog("1", started_at=_at(2)), _worklog("2", started_at=_at(18))]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [a.spent_seconds for a in board.assignees] == [10 * 3600]
        assert [d.seconds for d in board.effort_by_day] == [5 * 3600]

    async def test_an_epic_counts_as_an_item_but_never_as_its_own_child(
        self, session: AsyncSession
    ) -> None:
        """An epic is a Jira issue like any other, and the captions now say so."""
        await GoldRepository(session).upsert_items(
            [_epic("MYC-6"), _item("MYC-7", parent_key="MYC-6")]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 2, "done": 0}
        assert [a.items for a in board.assignees] == [2]
        assert [(e.issue_key, e.items) for e in board.epics] == [("MYC-6", 1)]

    async def test_it_agrees_with_the_summarizer_about_the_same_week(
        self, session: AsyncSession
    ) -> None:
        """One code path, so there is nothing for them to disagree over."""
        await GoldRepository(session).upsert_items([_epic(), _item()])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert board.totals == window.totals
        assert board.assignees == window.by_assignee

    async def test_an_empty_project_is_an_empty_board(self, session: AsyncSession) -> None:
        """A project set up but not yet worked renders a blank page, not a 500."""
        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 0, "done": 0}
        assert (board.assignees, board.epics, board.overdue) == ([], [], [])


@needs_postgres
class TestPriorityKindAndActivity:
    """Priority, kind and the activity feed. All three are whole-project on purpose."""

    async def test_priorities_count_only_unfinished_work(self, session: AsyncSession) -> None:
        """A shipped Highest is not backlog pressure."""
        await GoldRepository(session).upsert_items(
            [
                _item("MYC-7", priority="Highest"),
                _item("MYC-8", priority="Highest", status_category="done"),
                _item("MYC-9", priority="Low"),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.priorities["Highest"] == 1
        assert board.priorities["Low"] == 1

    async def test_every_jira_priority_gets_a_row_zeroes_included(
        self, session: AsyncSession
    ) -> None:
        """A fixed set of keys, so the page renders a fixed set of bars."""
        await GoldRepository(session).upsert_items([_item("MYC-7", priority="High")])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert list(board.priorities)[:5] == ["Highest", "High", "Medium", "Low", "Lowest"]
        assert board.priorities["Lowest"] == 0

    async def test_an_item_with_no_priority_is_counted_not_dropped(
        self, session: AsyncSession
    ) -> None:
        """A site that hides the field is an ordinary configuration, not missing data."""
        await GoldRepository(session).upsert_items([_item("MYC-7", priority=None)])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.priorities["None"] == 1

    async def test_a_site_renaming_its_scheme_still_shows(self, session: AsyncSession) -> None:
        """Kept and appended, rather than dropped to fit Jira's five."""
        await GoldRepository(session).upsert_items([_item("MYC-7", priority="Blocker")])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.priorities["Blocker"] == 1

    async def test_kinds_are_the_whole_project_largest_first(self, session: AsyncSession) -> None:
        """What a team's work is made of does not change because a week was quiet."""
        await GoldRepository(session).upsert_items(
            [
                _epic(),
                _item("MYC-7", kind="task", updated_at=_at(2)),
                _item("MYC-8", kind="task", status_category="done"),
                _item("MYC-9", kind="story"),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [(k.kind, k.items, k.done) for k in board.kinds] == [
            ("task", 2, 1),
            ("epic", 1, 0),
            ("story", 1, 0),
        ]

    async def test_the_feed_is_newest_first_and_ignores_the_window(
        self, session: AsyncSession
    ) -> None:
        """The one block where an empty window would be a lie."""
        await GoldRepository(session).upsert_items(
            [
                _item("MYC-7", updated_at=_at(2)),
                _item("MYC-8", updated_at=_at(19)),
                _item("MYC-9", updated_at=_at(11)),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [r.issue_key for r in board.recent] == ["MYC-8", "MYC-9", "MYC-7"]

    async def test_the_feed_is_capped(self, session: AsyncSession) -> None:
        """A glance, not a table to scroll."""
        await GoldRepository(session).upsert_items(
            [_item(f"MYC-{n}", updated_at=_at(2, n)) for n in range(1, RECENT_LIMIT + 4)]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert len(board.recent) == RECENT_LIMIT


@needs_postgres
class TestSprintProgress:
    """The unit a team commits to, which the calendar heatmap is not."""

    async def test_a_sprint_counts_its_items_and_its_done(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items(
            [
                _item("MYC-7", sprint_id=2, sprint_name="Sprint 0", sprint_state="active"),
                _item(
                    "MYC-8",
                    sprint_id=2,
                    sprint_name="Sprint 0",
                    sprint_state="active",
                    status_category="done",
                ),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [(s.sprint_id, s.items, s.done, s.percent) for s in board.sprints] == [(2, 2, 1, 50)]

    async def test_the_backlog_is_not_a_sprint(self, session: AsyncSession) -> None:
        """An item nobody planned into a sprint would otherwise claim to be one."""
        await GoldRepository(session).upsert_items(
            [
                _item("MYC-7", sprint_id=2, sprint_name="Sprint 0", sprint_state="active"),
                _item("MYC-8"),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [s.sprint_id for s in board.sprints] == [2]
        assert board.sprints[0].items == 1

    async def test_sprints_come_back_newest_first(self, session: AsyncSession) -> None:
        """By id, not by name: "Sprint 10" sorts before "Sprint 2" and dates are not here."""
        await GoldRepository(session).upsert_items(
            [
                _item("MYC-7", sprint_id=2, sprint_name="Sprint 0", sprint_state="closed"),
                _item("MYC-8", sprint_id=3, sprint_name="Sprint 1", sprint_state="active"),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [s.sprint_id for s in board.sprints] == [3, 2]

    async def test_a_project_with_no_sprints_gets_an_empty_list(
        self, session: AsyncSession
    ) -> None:
        """A configuration, not a failure — the block says so rather than breaking."""
        await GoldRepository(session).upsert_items([_item("MYC-7")])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.sprints == []


@needs_postgres
class TestTheHeatmap:
    """`effort_by_day` over twelve weeks: whether anyone was working at all."""

    async def test_a_day_sums_every_worklog_on_it(self, session: AsyncSession) -> None:
        """Two logs on the same day are one cell worth both, not two cells."""
        await GoldRepository(session).upsert_worklogs(
            [
                _worklog("1", started_at=_at(18, 9), time_spent_seconds=3600),
                _worklog("2", started_at=_at(18, 17), time_spent_seconds=1800),
                _worklog("3", started_at=_at(19), time_spent_seconds=7200),
            ]
        )

        counted = await GoldRepository(session).effort_by_day(PROJECT, _at(1))
        assert [(d.day.isoformat(), d.seconds) for d in counted] == [
            ("2026-09-18", 5400),
            ("2026-09-19", 7200),
        ]

    async def test_a_quiet_day_gets_no_row_at_all(self, session: AsyncSession) -> None:
        """Absent, not zero."""
        await GoldRepository(session).upsert_worklogs([_worklog("1", started_at=_at(18))])

        counted = await GoldRepository(session).effort_by_day(PROJECT, _at(1))
        assert [d.day.isoformat() for d in counted] == ["2026-09-18"]

    async def test_it_reaches_further_back_than_the_window(self, session: AsyncSession) -> None:
        """Its own span, or a heatmap of seven cells is a bar chart wearing a grid."""
        await GoldRepository(session).upsert_worklogs(
            [
                _worklog("1", started_at=_at(2)),
                _worklog("2", started_at=_at(20)),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert {d.day.isoformat() for d in board.calendar} == {"2026-09-02", "2026-09-20"}

    async def test_the_window_chart_is_a_slice_of_the_same_worklogs(
        self, session: AsyncSession
    ) -> None:
        """Both halves of the block read one source, at two zooms."""
        await GoldRepository(session).upsert_worklogs(
            [
                _worklog("1", started_at=_at(2)),
                _worklog("2", started_at=_at(20)),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [d.day.isoformat() for d in board.effort_by_day] == ["2026-09-20"]
        assert len(board.calendar) == 2
