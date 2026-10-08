"""Query gold for the data one specific request needs."""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.repositories.gold import GoldRepository, WorkItemRow
from mycel.infra.postgres.repositories.gold_stats import AssigneeLoad, DayEffort, GoldStats

#: Most work items a prompt carries.
MAX_ITEMS = 300


@dataclass(frozen=True)
class ProgressWindow:
    """Everything the summariser is given about one project over one window."""

    project: str
    since: datetime
    until: datetime
    items: list[WorkItemRow]
    #: Epic key -> its children in this window.
    by_epic: dict[str, list[WorkItemRow]]
    #: Epic key -> its title, including epics that did not move in the window themselves.
    epic_titles: dict[str, str]
    #: Items that moved in the window, counted by the category they are in now.
    totals: dict[str, int]
    by_assignee: list[AssigneeLoad]
    #: Past due and not done, across the **whole project** rather than the window.
    overdue: list[WorkItemRow]
    effort_by_day: list[DayEffort]
    #: Items dropped to fit `MAX_ITEMS`.
    dropped: int = 0
    #: Items with no epic above them.
    orphans: list[WorkItemRow] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Nothing moved. Not an error — a quiet week is an answer."""
        return not self.items


async def gather_progress(
    session: AsyncSession, project: str, since: datetime, until: datetime
) -> ProgressWindow:
    """One project's window, as the summariser will see it."""
    gold = GoldRepository(session)
    stats = GoldStats(session)

    items = await gold.items_between(project, since, until)
    # The newest items survive a truncation.
    dropped = max(0, len(items) - MAX_ITEMS)
    items = items[dropped:]

    by_epic, orphans = _group(items)
    parents = await gold.parents_of(project, list(by_epic))

    return ProgressWindow(
        project=project,
        since=since,
        until=until,
        items=items,
        by_epic=by_epic,
        epic_titles={row.issue_key: row.title for row in parents},
        totals=await stats.count_by_category(project, since, until),
        by_assignee=await stats.load_by_assignee(project, since, until),
        overdue=await stats.overdue(project, until),
        effort_by_day=await stats.effort_by_day(project, since, until),
        dropped=dropped,
        orphans=orphans,
    )


def _group(items: list[WorkItemRow]) -> tuple[dict[str, list[WorkItemRow]], list[WorkItemRow]]:
    """Children under their parent, and everything with no parent to sit under."""
    by_epic: dict[str, list[WorkItemRow]] = {}
    orphans: list[WorkItemRow] = []
    for item in items:
        if item.kind == "epic":
            by_epic.setdefault(item.issue_key, [])
        elif item.parent_key:
            by_epic.setdefault(item.parent_key, []).append(item)
        else:
            orphans.append(item)
    return by_epic, orphans
