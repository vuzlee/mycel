"""Assemble one project's picture from gold."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.repositories.gold import GoldRepository, WorkItemRow
from mycel.infra.postgres.repositories.gold_stats import (
    AssigneeLoad,
    DayEffort,
    GoldStats,
    KindTally,
    SprintTally,
)
from mycel.services.gather import gather_progress

#: Rows in the activity feed.
RECENT_LIMIT = 12

#: How far back the heatmap reaches, regardless of the chosen window.
HEATMAP_DAYS = 84


@dataclass(frozen=True)
class EpicProgress:
    """One epic and how far its children have got."""

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
    """What one project has been doing in one window."""

    project: str
    since: datetime
    until: datetime
    totals: dict[str, int]
    all_totals: dict[str, int]
    overdue: list[WorkItemRow]
    assignees: list[AssigneeLoad]
    epics: list[EpicProgress]
    effort_by_day: list[DayEffort]
    #: Unfinished items by priority, whole project.
    priorities: dict[str, int]
    #: What the project's work is made of, largest kind first.
    kinds: list[KindTally]
    #: The last things to move, newest first.
    recent: list[WorkItemRow]
    #: Every sprint with work in it, newest first.
    sprints: list[SprintTally]
    #: Effort logged per day over `HEATMAP_DAYS`, oldest first, days with nothing left out.
    calendar: list[DayEffort]

    @property
    def percent(self) -> int:
        """The project, 0-100, by items done over items that exist."""
        total = sum(self.all_totals.values())
        return round(100 * self.all_totals.get("done", 0) / total) if total else 0


async def build_dashboard(
    session: AsyncSession, project: str, since: datetime, until: datetime
) -> Dashboard:
    """The whole picture, from the same window the summarizer is given."""
    window = await gather_progress(session, project, since, until)
    gold = GoldRepository(session)
    stats = GoldStats(session)

    # Every epic, not only moving ones: an unstarted epic is a row at zero.
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
        all_totals=await stats.totals_all_time(project),
        overdue=window.overdue,
        assignees=window.by_assignee,
        epics=[
            EpicProgress(
                issue_key=epic.issue_key,
                title=epic.title,
                status_category=epic.status_category,
                items=len(by_parent[epic.issue_key]),
                done=sum(1 for c in by_parent[epic.issue_key] if c.status_category == "done"),
                moved=len(window.by_epic.get(epic.issue_key, [])),
                moved_done=sum(
                    1 for c in window.by_epic.get(epic.issue_key, []) if c.status_category == "done"
                ),
            )
            for epic in epics
        ],
        effort_by_day=window.effort_by_day,
        priorities=await stats.count_by_priority(project),
        kinds=await stats.count_by_kind(project),
        recent=await gold.recently_updated(project, RECENT_LIMIT),
        sprints=await stats.count_by_sprint(project),
        calendar=await stats.effort_by_day(project, until - timedelta(days=HEATMAP_DAYS)),
    )


async def list_projects(session: AsyncSession) -> list[str]:
    """Every project with work in it, for the picker."""
    return await GoldRepository(session).projects()
