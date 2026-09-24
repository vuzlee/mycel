"""Business-aggregated tables. The only layer agents are allowed to read.

All SQL for gold lives here: callers ask for `items_between(...)`, never assemble a query.
Changing a column changes the contract those callers depend on — adding is free, dropping
or redefining is a two-release move.

Every aggregate is computed in the database. A project that has been running a year would
otherwise drag every row across the wire to produce a table with one line per person.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import Select, func, select
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
SECONDS_PER_DAY = 8 * 3600


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


@dataclass(frozen=True)
class AssigneeLoad:
    """One person's window: how much they took on, and how it compares to the estimate.

    `spent` comes from the issues assigned to them rather than from worklogs, because the
    question here is "is this person's plate over-full", not "who did the typing".

    That has a consequence worth stating wherever these numbers are shown. The **window
    chooses the issues**; the figures on each issue are Jira's running totals for its whole
    life. A ticket touched yesterday brings in every hour ever logged against it, not the
    hours logged this week. `effort_by_day` is the opposite — it sums worklogs *dated*
    inside the window — so the two blocks can legitimately disagree, and a screen that
    shows both owes the reader that sentence.
    """

    account_id: str | None
    name: str
    items: int
    done: int
    estimated_seconds: int
    spent_seconds: int

    @property
    def gap_seconds(self) -> int:
        """Spent minus estimated. Positive means over, which is the number nobody has."""
        return self.spent_seconds - self.estimated_seconds


@dataclass(frozen=True)
class KindTally:
    """How much work of one kind there is, and how much of it is finished."""

    kind: str
    items: int
    done: int


@dataclass(frozen=True)
class DayEffort:
    """Hours logged on one day, across everybody."""

    day: date
    seconds: int


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
        return [_item(row) for row in result]

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
        return [_item(row) for row in await self._session.scalars(query)]

    async def count_by_category(
        self, project: str, since: datetime, until: datetime | None = None
    ) -> dict[str, int]:
        """How many items sit in each status category. Every category, zeroes included.

        Counts what moved in the window, by the category it is in *now* — not what changed
        category during it. Jira stamps a transition with the moment of the API call, so
        the second question cannot be answered honestly and is not asked.

        Every issue type counts as one, epics included: an epic is a Jira issue with a
        status like any other, and filtering it out here would make these totals disagree
        with `load_by_assignee`, which does not filter either.
        """
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
        """Per person: how many items, how many finished, estimated against spent.

        Busiest first. Unassigned work is a row of its own rather than being dropped —
        a sprint with six unassigned tickets is exactly what a lead needs to see.
        """
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
        """Due before now and not done, soonest-due first — the most late at the top.

        Nothing about status history is consulted, only the due date and the current
        category: Jira stamps a transition with the moment of the API call, so for any
        issue entered after the fact "how long has it been like this" would be a lie.
        """
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
        return [_item(row) for row in await self._session.scalars(query)]

    async def effort_by_day(
        self, project: str, since: datetime, until: datetime | None = None
    ) -> list[DayEffort]:
        """Seconds logged per day, oldest first.

        From worklogs rather than from resolution dates. A worklog's `started` is whatever
        it was told, so it survives a project filled in retroactively; `resolved_at` is
        stamped by Jira and would put a month of work on the day it was entered.

        Days with nothing logged get no row. The heatmap calls this over its own longer
        span and draws its own calendar, so it has to fill the gaps anyway, and sending
        three months of zeroes to say nothing happened is the wrong shape for the wire.
        """
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
        """Unfinished items by priority, whole project. Every known priority, zeroes included.

        Unfinished rather than all: the question a priority answers is "what should be
        picked up next", and a finished item has no next. Counting done work here would
        make a project that shipped its urgent tickets look like it is drowning in them.

        Whole project rather than a window, for the same reason `overdue` is: a Highest
        nobody has touched in a month is exactly the one worth seeing.
        """
        query = (
            select(WorkItem.priority, func.count())
            .where(WorkItem.project == project, WorkItem.status_category != "done")
            .group_by(WorkItem.priority)
        )
        # Grouped on the raw column and renamed here, not `coalesce`d in SQL: Postgres
        # compares a GROUP BY expression to the selected one textually, and SQLAlchemy
        # gives the two `coalesce` calls separate bind parameters, so they do not match.
        counted = {
            (UNPRIORITISED if p is None else str(p)): int(n)
            for p, n in (await self._session.execute(query)).all()
        }
        # Jira's own order first, then whatever the site added, so a renamed scheme still
        # shows rather than being silently dropped to fit a fixed list.
        known = {name: counted.pop(name, 0) for name in PRIORITIES}
        return {**known, **counted}

    async def count_by_kind(self, project: str) -> list[KindTally]:
        """Every kind of work in the project, largest first, with how much is finished.

        Whole project: a breakdown of what this team's work is *made of* does not change
        because a week was quiet, and reading it through a window says it does.
        """
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
        return [_item(row) for row in await self._session.scalars(query)]

    async def totals_all_time(self, project: str) -> dict[str, int]:
        """Every item in the project by category, no window. Every category, zeroes included.

        The denominator a progress bar needs. `count_by_category` counts what moved in a
        window, which is the wrong bottom half of a fraction: a quiet week would draw the
        project as nearly finished because only two tickets moved and one of them was done.
        """
        query = (
            select(WorkItem.status_category, func.count())
            .where(WorkItem.project == project)
            .group_by(WorkItem.status_category)
        )
        counted = {str(c): int(n) for c, n in (await self._session.execute(query)).all()}
        return {category: counted.get(category, 0) for category in CATEGORIES}

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
        return [_item(row) for row in await self._session.scalars(query)]

    async def epics(self, project: str) -> list[WorkItemRow]:
        """Every epic in the project, whether or not anything under it moved."""
        query = (
            select(WorkItem)
            .where(WorkItem.project == project, WorkItem.kind == "epic")
            .order_by(WorkItem.issue_key)
        )
        return [_item(row) for row in await self._session.scalars(query)]

    async def projects(self) -> list[str]:
        """Every project with work in it, for the picker."""
        query: Select[tuple[str]] = select(WorkItem.project).distinct().order_by(WorkItem.project)
        return [str(p) for p in (await self._session.scalars(query)).all()]


def _item(row: WorkItem) -> WorkItemRow:
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
