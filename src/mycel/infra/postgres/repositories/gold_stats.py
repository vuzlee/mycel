"""Read-only aggregates over gold, computed in the database."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import WorkItem, Worklog
from mycel.infra.postgres.repositories.gold import (
    CATEGORIES,
    PRIORITIES,
    UNPRIORITIZED,
    WorkItemRow,
    to_row,
)


@dataclass(frozen=True)
class AssigneeLoad:
    """One person's items in a window, estimated against spent from the issues assigned to them."""

    account_id: str | None
    name: str
    items: int
    done: int
    estimated_seconds: int
    spent_seconds: int

    @property
    def gap_seconds(self) -> int:
        """Spent minus estimated; positive means over."""
        return self.spent_seconds - self.estimated_seconds


@dataclass(frozen=True)
class KindTally:
    """Work of one kind: how much, and how much is finished."""

    kind: str
    items: int
    done: int


@dataclass(frozen=True)
class SprintTally:
    """One sprint, its completion, and lifetime effort logged on its issues."""

    sprint_id: int
    name: str
    state: str
    items: int
    done: int

    @property
    def percent(self) -> int:
        """Completion percent, 0-100; an empty sprint reads as 0."""
        return round(100 * self.done / self.items) if self.items else 0


@dataclass(frozen=True)
class DayEffort:
    """Hours logged on one day, across everybody."""

    day: date
    seconds: int


class GoldStats:
    """Aggregates over gold on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_by_category(
        self, project: str, since: datetime, until: datetime | None = None
    ) -> dict[str, int]:
        """Items that moved in the window, by their current status category, zeros included."""
        query = (
            select(WorkItem.status_category, func.count())
            .where(WorkItem.project == project, WorkItem.updated_at >= since)
            .group_by(WorkItem.status_category)
        )
        if until is not None:
            query = query.where(WorkItem.updated_at < until)
        counted = {str(c): int(n) for c, n in (await self._session.execute(query)).all()}
        return {category: counted.get(category, 0) for category in CATEGORIES}

    async def load_by_assignee(
        self, project: str, since: datetime, until: datetime | None = None
    ) -> list[AssigneeLoad]:
        """Per person: items, finished, estimated vs spent. Busiest first; unassigned kept."""
        query = (
            select(
                WorkItem.assignee_account_id,
                func.max(func.coalesce(WorkItem.assignee_name, "Unassigned")),
                func.count(),
                func.count().filter(WorkItem.status_category == "done"),
                func.coalesce(func.sum(WorkItem.original_estimate_seconds), 0),
                func.coalesce(func.sum(WorkItem.time_spent_seconds), 0),
            )
            .where(WorkItem.project == project, WorkItem.updated_at >= since)
            .group_by(WorkItem.assignee_account_id)
        )
        if until is not None:
            query = query.where(WorkItem.updated_at < until)

        rows = [
            AssigneeLoad(
                account_id=account_id,
                name=str(name),
                items=int(items),
                done=int(done),
                estimated_seconds=int(estimated),
                spent_seconds=int(spent),
            )
            for account_id, name, items, done, estimated, spent in (
                await self._session.execute(query)
            ).all()
        ]
        return sorted(rows, key=lambda r: (-r.items, r.name))

    async def overdue(self, project: str, asof: datetime) -> list[WorkItemRow]:
        """Due before now and not done, soonest-due first."""
        query = (
            select(WorkItem)
            .where(
                WorkItem.project == project,
                WorkItem.due_at.is_not(None),
                WorkItem.due_at < asof,
                WorkItem.status_category != "done",
            )
            .order_by(WorkItem.due_at)
        )
        return [to_row(row) for row in await self._session.scalars(query)]

    async def effort_by_day(
        self, project: str, since: datetime, until: datetime | None = None
    ) -> list[DayEffort]:
        """Seconds logged per day from worklogs, oldest first."""
        day = func.date(Worklog.started_at).label("day")
        query = (
            select(day, func.coalesce(func.sum(Worklog.time_spent_seconds), 0))
            .where(Worklog.project == project, Worklog.started_at >= since)
            .group_by(day)
            .order_by(day)
        )
        if until is not None:
            query = query.where(Worklog.started_at < until)
        return [
            DayEffort(day=d, seconds=int(seconds))
            for d, seconds in (await self._session.execute(query)).all()
        ]

    async def count_by_priority(self, project: str) -> dict[str, int]:
        """Unfinished items by priority, whole project, every known priority included."""
        query = (
            select(WorkItem.priority, func.count())
            .where(WorkItem.project == project, WorkItem.status_category != "done")
            .group_by(WorkItem.priority)
        )
        # Group on the raw column: two `coalesce` calls get separate binds and won't match.
        counted = {
            (UNPRIORITIZED if p is None else str(p)): int(n)
            for p, n in (await self._session.execute(query)).all()
        }
        # Known priorities first, then any the site added.
        known = {name: counted.pop(name, 0) for name in PRIORITIES}
        return {**known, **counted}

    async def count_by_kind(self, project: str) -> list[KindTally]:
        """Every kind of work in the project, largest first, with how much is finished."""
        query = (
            select(
                WorkItem.kind,
                func.count(),
                func.count().filter(WorkItem.status_category == "done"),
            )
            .where(WorkItem.project == project)
            .group_by(WorkItem.kind)
        )
        rows = [
            KindTally(kind=str(kind), items=int(items), done=int(done))
            for kind, items, done in (await self._session.execute(query)).all()
        ]
        return sorted(rows, key=lambda r: (-r.items, r.kind))

    async def count_by_sprint(self, project: str) -> list[SprintTally]:
        """Every sprint with work in it, newest first, with completion; the backlog is excluded."""
        query = (
            select(
                WorkItem.sprint_id,
                func.max(WorkItem.sprint_name),
                func.max(WorkItem.sprint_state),
                func.count(),
                func.count().filter(WorkItem.status_category == "done"),
            )
            .where(WorkItem.project == project, WorkItem.sprint_id.is_not(None))
            .group_by(WorkItem.sprint_id)
            .order_by(WorkItem.sprint_id.desc())
        )
        return [
            SprintTally(
                sprint_id=int(sprint_id),
                name=str(name or f"Sprint {sprint_id}"),
                state=str(state or "unknown"),
                items=int(items),
                done=int(done),
            )
            for sprint_id, name, state, items, done in (await self._session.execute(query)).all()
        ]

    async def totals_all_time(self, project: str) -> dict[str, int]:
        """Every item in the project by category, no window, zeros included."""
        query = (
            select(WorkItem.status_category, func.count())
            .where(WorkItem.project == project)
            .group_by(WorkItem.status_category)
        )
        counted = {str(c): int(n) for c, n in (await self._session.execute(query)).all()}
        return {category: counted.get(category, 0) for category in CATEGORIES}
