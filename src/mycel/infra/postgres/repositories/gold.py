"""Business-aggregated tables. The only layer agents are allowed to read.

All SQL for gold lives here: callers ask for `items_between(...)`, never assemble a query.
Changing a column changes the contract those callers depend on — adding is free, dropping
or redefining is a two-release move.

Every aggregate is computed in the database. A project that has been running a year would
otherwise drag every row across the wire to produce a table with one line per person.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import WorkItem, Worklog

#: Jira's own status rollup, in the order a board reads left to right. Every caller gets
#: all three even at zero, so a page renders a fixed set of columns without deciding what
#: a missing key means.
CATEGORIES = ("todo", "doing", "done")

#: Jira's default priority scheme, most urgent first. A site that renamed or added one
#: still counts: an unrecognised name is kept and sorted after these, and an issue with no
#: priority is counted under `UNPRIORITISED` rather than dropped.
PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")

#: What an item with no priority set is counted as. A name rather than None, because the
#: caller is a chart and a bar needs a label.
UNPRIORITISED = "None"

#: What one work item is worth in a day, for turning seconds into man-days. Jira's own
#: default working day, and the unit a plan is actually discussed in.
WORKDAY_SECONDS = 8 * 3600


@dataclass(frozen=True)
class WorkItemRow:
    """One piece of tracked work, as callers outside the infra layer see it."""

    source: str
    project: str
    issue_id: str
    issue_key: str
    kind: str
    parent_key: str | None
    title: str
    status: str
    status_category: str
    priority: str | None
    #: The sprint the item is in *now*, not every sprint it has ever been in — see
    #: migration 0011 for why the rollover history is dropped. None is the backlog.
    sprint_id: int | None
    sprint_name: str | None
    sprint_state: str | None
    assignee_account_id: str | None
    assignee_name: str | None
    original_estimate_seconds: int | None
    time_spent_seconds: int | None
    due_at: datetime | None
    created_at: datetime
    resolved_at: datetime | None
    labels: list[str]
    updated_at: datetime


@dataclass(frozen=True)
class WorklogRow:
    """One logged entry, on the day it was logged for."""

    source: str
    project: str
    worklog_id: str
    issue_key: str
    author_account_id: str | None
    author_name: str | None
    time_spent_seconds: int
    started_at: datetime
    comment: str | None


class GoldRepository:
    """Reads and writes gold, on a session someone else owns.

    Takes the session rather than opening one, so a caller can put several repository
    calls in a single transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_items(self, rows: Sequence[WorkItemRow]) -> int:
        """Write work items, replacing any that share `(source, issue_key)`.

        Upsert because a sync window overlaps the last one and because an issue is a
        record that keeps changing — the second write of a key is the newer truth.
        """
        if not rows:
            return 0
        stmt = insert(WorkItem).values([asdict(row) for row in rows])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_work_item_natural_key",
            set_={
                name: getattr(stmt.excluded, name)
                for name in asdict(rows[0])
                if name not in ("source", "issue_key")
            },
        )
        await self._session.execute(stmt)
        return len(rows)

    async def upsert_worklogs(self, rows: Sequence[WorklogRow]) -> int:
        """Write logged entries, replacing any that share `(source, worklog_id)`."""
        if not rows:
            return 0
        stmt = insert(Worklog).values([asdict(row) for row in rows])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_worklog_natural_key",
            set_={
                name: getattr(stmt.excluded, name)
                for name in asdict(rows[0])
                if name not in ("source", "worklog_id")
            },
        )
        await self._session.execute(stmt)
        return len(rows)

    async def items_between(
        self, project: str, since: datetime, until: datetime | None = None
    ) -> list[WorkItemRow]:
        """Everything that moved in a window, oldest first.

        "Moved" is `updated_at`, not `created_at`: a story opened last month and finished
        this week belongs in this week's report, and one opened this week and untouched
        since does not stop belonging to it.
        """
        query = select(WorkItem).where(WorkItem.project == project, WorkItem.updated_at >= since)
        if until is not None:
            query = query.where(WorkItem.updated_at < until)
        result = await self._session.scalars(query.order_by(WorkItem.updated_at))
        return [to_row(row) for row in result]

    async def parents_of(self, project: str, keys: Sequence[str]) -> list[WorkItemRow]:
        """The epics a window's items hang off, whether or not they moved themselves.

        An epic rarely changes while its children do, so it falls outside the window and
        the hierarchy would come back with holes where the parent names should be.
        """
        if not keys:
            return []
        query = select(WorkItem).where(
            WorkItem.project == project, WorkItem.issue_key.in_(list(keys))
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def recently_updated(self, project: str, limit: int) -> list[WorkItemRow]:
        """The last things to move, newest first, whole project.

        Not windowed, unlike everything else that reads `updated_at`. A window that turns
        up empty is an answer for a count and a wrong one here: "nothing happened" is what
        a reader concludes about the project, when the truth is that the last thing to
        happen was eight days ago and is worth naming.
        """
        query = (
            select(WorkItem)
            .where(WorkItem.project == project)
            .order_by(WorkItem.updated_at.desc())
            .limit(limit)
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def children_of(self, project: str, keys: Sequence[str]) -> list[WorkItemRow]:
        """Every child of the given epics, whole project rather than a window.

        Same reason as `totals_all_time`: an epic's completion is a fraction of all its
        children, and counting only the ones that moved this week makes a quiet epic look
        finished.
        """
        if not keys:
            return []
        query = select(WorkItem).where(
            WorkItem.project == project, WorkItem.parent_key.in_(list(keys))
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def epics(self, project: str) -> list[WorkItemRow]:
        """Every epic in the project, whether or not anything under it moved."""
        query = (
            select(WorkItem)
            .where(WorkItem.project == project, WorkItem.kind == "epic")
            .order_by(WorkItem.issue_key)
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def projects(self) -> list[str]:
        """Every project with work in it, for the picker."""
        query: Select[tuple[str]] = select(WorkItem.project).distinct().order_by(WorkItem.project)
        return [str(p) for p in (await self._session.scalars(query)).all()]


def to_row(row: WorkItem) -> WorkItemRow:
    """The mapped row as the dataclass callers outside infra see."""
    return WorkItemRow(
        source=row.source,
        project=row.project,
        issue_id=row.issue_id,
        issue_key=row.issue_key,
        kind=row.kind,
        parent_key=row.parent_key,
        title=row.title,
        status=row.status,
        status_category=row.status_category,
        priority=row.priority,
        sprint_id=row.sprint_id,
        sprint_name=row.sprint_name,
        sprint_state=row.sprint_state,
        assignee_account_id=row.assignee_account_id,
        assignee_name=row.assignee_name,
        original_estimate_seconds=row.original_estimate_seconds,
        time_spent_seconds=row.time_spent_seconds,
        due_at=row.due_at,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        labels=list(row.labels or []),
        updated_at=row.updated_at,
    )
