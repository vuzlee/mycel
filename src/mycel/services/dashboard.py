"""Assemble one project's picture from gold.

Reads only. Every count is produced by the database — see `GoldRepository.load_by_assignee`
for why that matters — and this layer only joins the answers together.

It reuses `gather_progress` rather than querying gold itself. The dashboard and the report
must not be able to disagree about what happened this week, and two code paths asking the
same question is how they start to.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.repositories.gold import (
    AssigneeLoad,
    DayEffort,
    GoldRepository,
    WorkItemRow,
)
from mycel.services.gather import gather_progress


@dataclass(frozen=True)
class EpicProgress:
    """One epic and how far its children have got.

    The level a plan is discussed at. An epic with no children in the window still gets a
    row at zero, because "nothing happened on that epic" is the answer somebody came for.

    Two pairs of numbers, not one. `items`/`done` is the whole epic, which is what a
    progress bar can honestly be drawn from; `moved`/`moved_done` is this window, which is
    what tells you whether anyone touched it lately. A single pair would have to be one or
    the other, and each answers a question the other cannot.
    """

    issue_key: str
    title: str
    status_category: str
    items: int
    done: int
    moved: int
    moved_done: int

    @property
    def percent(self) -> int:
        """How far along, 0-100. An epic with no children reads as 0, not as finished."""
        return round(100 * self.done / self.items) if self.items else 0


@dataclass(frozen=True)
class Dashboard:
    """What one project has been doing in one window.

    `overdue` is a list rather than a count: the point of the screen is that a late ticket
    is visible without hunting, and a number is something you then have to go and expand.

    `totals` is the window and `all_totals` is the project. Both, because the first
    answers "what happened this week" and the second "how far are we" — a screen carrying
    only the window can be read as a project nearly done when it was merely a quiet week.
    """

    project: str
    since: datetime
    until: datetime
    totals: dict[str, int]
    all_totals: dict[str, int]
    overdue: list[WorkItemRow]
    assignees: list[AssigneeLoad]
    epics: list[EpicProgress]
    effort_by_day: list[DayEffort]

    @property
    def percent(self) -> int:
        """The project, 0-100, by items done over items that exist."""
        total = sum(self.all_totals.values())
        return round(100 * self.all_totals.get("done", 0) / total) if total else 0


async def build_dashboard(
    session: AsyncSession, project: str, since: datetime, until: datetime
) -> Dashboard:
    """The whole picture, from the same window the summariser is given."""
    window = await gather_progress(session, project, since, until)
    gold = GoldRepository(session)

    # Every epic, not only the ones with movement: an epic nobody has started is a row at
    # zero, and leaving it out is how a plan looks shorter than it is.
    epics = await gold.epics(project)
    children = await gold.children_of(project, [epic.issue_key for epic in epics])
    by_parent: dict[str, list[WorkItemRow]] = {epic.issue_key: [] for epic in epics}
    for child in children:
        if child.parent_key in by_parent:
            by_parent[child.parent_key].append(child)

    return Dashboard(
        project=window.project,
        since=window.since,
        until=window.until,
        totals=window.totals,
        all_totals=await gold.totals_all_time(project),
        overdue=window.overdue,
        assignees=window.by_assignee,
        epics=[
            EpicProgress(
                issue_key=epic.issue_key,
                title=epic.title,
                status_category=epic.status_category,
                items=len(by_parent[epic.issue_key]),
                done=sum(
                    1 for c in by_parent[epic.issue_key] if c.status_category == "done"
                ),
                moved=len(window.by_epic.get(epic.issue_key, [])),
                moved_done=sum(
                    1
                    for c in window.by_epic.get(epic.issue_key, [])
                    if c.status_category == "done"
                ),
            )
            for epic in epics
        ],
        effort_by_day=window.effort_by_day,
    )


async def list_projects(session: AsyncSession) -> list[str]:
    """Every project with work in it, for the picker."""
    return await GoldRepository(session).projects()
