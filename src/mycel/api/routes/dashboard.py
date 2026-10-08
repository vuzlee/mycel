"""Read one project's progress: the part of this system a person can just look at."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from mycel.api.dependencies import CurrentUser
from mycel.infra.postgres.repositories.gold import WorkItemRow
from mycel.services.dashboards import DEFAULT_DAYS, get_dashboard
from mycel.services.permission import NotReadable

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

#: Longest window a caller may ask for.
MAX_DAYS = 90


class ItemResponse(BaseModel):
    """One work item, as a page lists it."""

    issue_key: str
    kind: str
    title: str
    status: str
    status_category: str
    priority: str | None = None
    assignee_name: str | None = None
    original_estimate_seconds: int | None = None
    time_spent_seconds: int | None = None
    due_at: datetime | None = None
    updated_at: datetime | None = None


class AssigneeResponse(BaseModel):
    """One person's row, summed over the window's items."""

    account_id: str | None = None
    name: str
    items: int
    done: int
    estimated_seconds: int
    spent_seconds: int
    gap_seconds: int


class EpicResponse(BaseModel):
    """One epic's row: how much sits under it, and how much of that is finished."""

    issue_key: str
    title: str
    status_category: str
    items: int
    done: int
    percent: int
    moved: int
    moved_done: int


class KindResponse(BaseModel):
    """One kind of work — epic, story, task, subtask — and how much of it is done."""

    kind: str
    items: int
    done: int


class SprintResponse(BaseModel):
    """One sprint and how much of it is finished."""

    sprint_id: int
    name: str
    state: str
    items: int
    done: int
    percent: int


class DayResponse(BaseModel):
    """Seconds logged on one day, across everybody."""

    day: str
    seconds: int


class DashboardResponse(BaseModel):
    """What one project has been doing, in the window asked for."""

    project: str
    since: datetime
    until: datetime
    percent: int = Field(
        description="The project finished, 0-100, by items done over items that exist."
    )
    all_totals: dict[str, int] = Field(
        description="Every item in the project by category, no window."
    )
    totals: dict[str, int] = Field(
        description="Items that moved in the window, by current status category: todo, doing, done."
    )
    priorities: dict[str, int] = Field(
        description="Unfinished items by priority name, whole project."
    )
    kinds: list[KindResponse] = Field(
        description="What the project's work is made of, largest kind first, whole project."
    )
    recent: list[ItemResponse] = Field(
        description="The last items to move, newest first, whole project rather than the window."
    )
    sprints: list[SprintResponse] = Field(
        description="Every sprint with work in it, newest first, whole project."
    )
    calendar: list[DayResponse] = Field(
        description="Effort logged per day over the last twelve weeks, oldest first."
    )
    overdue: list[ItemResponse] = Field(
        description="Past its due date and not done, most overdue first."
    )
    assignees: list[AssigneeResponse] = Field(
        description="One row per person, over the window's items."
    )
    epics: list[EpicResponse] = Field(
        description="Every epic in the project, including ones nothing moved under."
    )
    effort_by_day: list[DayResponse] = Field(
        description="Logged effort per day, dated by the day the work was logged for."
    )


@router.get("/{project}", response_model=DashboardResponse)
async def read_dashboard(
    project: str,
    user: CurrentUser,
    days: int = Query(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS),
) -> DashboardResponse:
    """The numbers for one project."""
    try:
        board = await get_dashboard(user, project, days=days)
    except NotReadable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not your project"
        ) from None
    return DashboardResponse(
        project=board.project,
        since=board.since,
        until=board.until,
        percent=board.percent,
        all_totals=board.all_totals,
        totals=board.totals,
        priorities=board.priorities,
        kinds=[KindResponse(kind=k.kind, items=k.items, done=k.done) for k in board.kinds],
        recent=[_item(row) for row in board.recent],
        sprints=[
            SprintResponse(
                sprint_id=s.sprint_id,
                name=s.name,
                state=s.state,
                items=s.items,
                done=s.done,
                percent=s.percent,
            )
            for s in board.sprints
        ],
        calendar=[DayResponse(day=d.day.isoformat(), seconds=d.seconds) for d in board.calendar],
        overdue=[_item(row) for row in board.overdue],
        assignees=[
            AssigneeResponse(
                account_id=a.account_id,
                name=a.name,
                items=a.items,
                done=a.done,
                estimated_seconds=a.estimated_seconds,
                spent_seconds=a.spent_seconds,
                gap_seconds=a.gap_seconds,
            )
            for a in board.assignees
        ],
        epics=[
            EpicResponse(
                issue_key=e.issue_key,
                title=e.title,
                status_category=e.status_category,
                items=e.items,
                done=e.done,
                percent=e.percent,
                moved=e.moved,
                moved_done=e.moved_done,
            )
            for e in board.epics
        ],
        effort_by_day=[
            DayResponse(day=d.day.isoformat(), seconds=d.seconds) for d in board.effort_by_day
        ],
    )


def _item(row: WorkItemRow) -> ItemResponse:
    """A gold row as the page sees it. Seconds stay seconds; days are the UI's decision."""
    return ItemResponse(
        issue_key=row.issue_key,
        kind=row.kind,
        title=row.title,
        status=row.status,
        status_category=row.status_category,
        priority=row.priority,
        assignee_name=row.assignee_name,
        original_estimate_seconds=row.original_estimate_seconds,
        time_spent_seconds=row.time_spent_seconds,
        due_at=row.due_at,
        updated_at=row.updated_at,
    )
