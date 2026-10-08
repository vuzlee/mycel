"""Gold reads and writes, the only layer agents may read. All gold SQL lives here."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import WorkItem, Worklog
from mycel.infra.postgres.repositories._sql import upsert

#: Jira status categories in board order; every caller gets all three, zeros included.
CATEGORIES = ("todo", "doing", "done")

#: Jira's default priorities, most urgent first; unknown names sort after these.
PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")

#: Label for items with no priority.
UNPRIORITISED = "None"

#: Working seconds in one man-day (Jira's default working day).
WORKDAY_SECONDS = 8 * 3600


@dataclass(frozen=True)
class WorkItemRow:
    """One piece of tracked work, as callers outside infra see it."""

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
    #: The current sprint only; None is the backlog.
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
    """Reads and writes gold on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_items(self, rows: Sequence[WorkItemRow]) -> int:
        return await upsert(self._session, WorkItem, rows, "uq_work_item_natural_key", "issue_key")

    async def upsert_worklogs(self, rows: Sequence[WorklogRow]) -> int:
        return await upsert(self._session, Worklog, rows, "uq_worklog_natural_key", "worklog_id")

    async def items_between(
        self, project: str, since: datetime, until: datetime | None = None
    ) -> list[WorkItemRow]:
        """Items whose `updated_at` falls in the window, oldest first."""
        query = select(WorkItem).where(WorkItem.project == project, WorkItem.updated_at >= since)
        if until is not None:
            query = query.where(WorkItem.updated_at < until)
        result = await self._session.scalars(query.order_by(WorkItem.updated_at))
        return [to_row(row) for row in result]

    async def parents_of(self, project: str, keys: Sequence[str]) -> list[WorkItemRow]:
        """Epics of the given items, whether or not they moved in the window."""
        if not keys:
            return []
        query = select(WorkItem).where(
            WorkItem.project == project, WorkItem.issue_key.in_(list(keys))
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def recently_updated(self, project: str, limit: int) -> list[WorkItemRow]:
        """The most recently updated items, newest first, whole project."""
        query = (
            select(WorkItem)
            .where(WorkItem.project == project)
            .order_by(WorkItem.updated_at.desc())
            .limit(limit)
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def children_of(self, project: str, keys: Sequence[str]) -> list[WorkItemRow]:
        """Every child of the given epics, whole project."""
        if not keys:
            return []
        query = select(WorkItem).where(
            WorkItem.project == project, WorkItem.parent_key.in_(list(keys))
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def epics(self, project: str) -> list[WorkItemRow]:
        """Every epic in the project."""
        query = (
            select(WorkItem)
            .where(WorkItem.project == project, WorkItem.kind == "epic")
            .order_by(WorkItem.issue_key)
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def projects(self) -> list[str]:
        """Every project with work in it."""
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
