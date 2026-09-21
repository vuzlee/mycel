"""Query gold for the data one specific request needs.

Reads gold only. This is the single point where data leaves the database for the AI layer,
and no new SQL is written here: every query already exists on a repository.

**The window goes into the prompt, not behind a tool.** The alternative is a `query_work`
tool the summariser calls, which costs several model round-trips per report; the cloud
tier this runs on allows 20 requests a day. A sprint's issues are a few hundred rows and
fit in a prompt with room to spare.

That only holds while the window is small, so the window truncates and *says so* — a
report that quietly summarises half a sprint is worse than one that states its own limit.

The derived facts — totals, load per person, what is overdue, effort per day — are
computed in SQL rather than left for the model to count. Arithmetic is the one thing a
database is certain about and a language model is not, and what is left over is the part
that needs judgement: which of six late tickets to mention first.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.repositories.gold import (
    AssigneeLoad,
    DayEffort,
    GoldRepository,
    WorkItemRow,
)

#: Most work items a prompt carries. Past this the oldest are dropped and the prompt says
#: how many: a ceiling that is visible in the output is a limit, one that is not is a bug.
MAX_ITEMS = 300


@dataclass(frozen=True)
class ProgressWindow:
    """Everything the summariser is given about one project over one window.

    Frozen, and assembled in one place, so what the model saw is reconstructable from the
    call that produced it rather than from whatever the prompt happened to read.
    """

    project: str
    since: datetime
    until: datetime
    items: list[WorkItemRow]
    #: Epic key -> its children in this window. Resolved once here so neither the prompt
    #: nor the dashboard has to walk `parent_key` itself and disagree about the answer.
    by_epic: dict[str, list[WorkItemRow]]
    #: Epic key -> its title, including epics that did not move in the window themselves.
    epic_titles: dict[str, str]
    #: Items that moved in the window, counted by the category they are in now.
    totals: dict[str, int]
    by_assignee: list[AssigneeLoad]
    #: Past due and not done, across the **whole project** rather than the window. An item
    #: overdue since last month and untouched since is the one most worth seeing, and a
    #: window filter is exactly what would hide it.
    overdue: list[WorkItemRow]
    effort_by_day: list[DayEffort]
    #: Items dropped to fit `MAX_ITEMS`. Non-zero means the summary is partial, and the
    #: prompt says so rather than letting the model claim completeness.
    dropped: int = 0
    #: Items with no epic above them. Not an error — a standalone task is ordinary work.
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

    items = await gold.items_between(project, since, until)
    # The newest survive a truncation: a summary of this sprint that omits yesterday is
    # the wrong half to keep.
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
        totals=await gold.count_by_category(project, since, until),
        by_assignee=await gold.load_by_assignee(project, since, until),
        overdue=await gold.overdue(project, until),
        effort_by_day=await gold.effort_by_day(project, since, until),
        dropped=dropped,
        orphans=orphans,
    )


def _group(items: list[WorkItemRow]) -> tuple[dict[str, list[WorkItemRow]], list[WorkItemRow]]:
    """Children under their parent, and everything with no parent to sit under.

    One level, not a tree. Jira allows subtask under story under epic, but a report is read
    top-down and a three-deep nesting on a page is a thing people stop unfolding — so a
    subtask is listed under the epic its story belongs to, or on its own if it has none.
    """
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
