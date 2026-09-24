"""Read one project's progress: the part of this system a person can just look at.

Synchronous, unlike `/chat`. A question is minutes of agent work and gets a job id; a
board is a handful of counting queries, so it answers in the request and needs no receipt.

    GET  /dashboard/{project}   the numbers, as JSON

Every field says its own scope, because they are not all the same one: some blocks are the
window and some are the whole project, and which is which is invisible from the figures.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from mycel.api.dependencies import current_user
from mycel.domains.dashboard import DEFAULT_DAYS, get_dashboard
from mycel.infra.postgres.repositories.gold import WorkItemRow
from mycel.services.auth import Principal
from mycel.services.permission import can_read_project

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

#: Longest window a caller may ask for. Not a performance limit — the counting is in SQL —
#: but a year of history on one screen is not a dashboard, it is an export.
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
    """One person's row, summed over the window's items.

    `gap_seconds` is spent minus estimated: positive means over the estimate. Seconds
    throughout — man-days are a display decision and belong to whatever renders this.

    The window picks *which* issues are summed, not which hours: these are Jira's lifetime
    totals on each issue. `effort_by_day` counts worklogs dated inside the window instead,
    so the two are not two views of one number.
    """

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
        description=(
            "The project finished, 0-100, by items done over items that exist. Whole "
            "project, never the window: a quiet week would otherwise read as nearly done."
        )
    )
    all_totals: dict[str, int] = Field(
        description=(
            "Every item in the project by category, no window. The denominator behind "
            "`percent`, given as well so a caller can show the parts it is made of."
        )
    )
    totals: dict[str, int] = Field(
        description=(
            "Items that moved in the window, counted by the status category they are in "
            "now: todo, doing, done. Not how many changed category during it — Jira dates "
            "a transition from the API call, so that question has no honest answer. Every "
            "issue type counts as one, epics included."
        )
    )
    priorities: dict[str, int] = Field(
        description=(
            "Unfinished items by priority name, whole project. Done work is left out: a "
            "priority answers 'what next', and a shipped ticket has no next. Jira's five "
            "come first even at zero, then whatever else the site uses; items with no "
            "priority set are counted under 'None'."
        )
    )
    kinds: list[KindResponse] = Field(
        description=(
            "What the project's work is made of, largest kind first, whole project. Not "
            "windowed: the shape of a team's work does not change because a week was quiet."
        )
    )
    recent: list[ItemResponse] = Field(
        description=(
            "The last items to move, newest first, whole project rather than the window — "
            "an empty feed would read as a dead project when the truth is that the last "
            "thing to happen was a fortnight ago and is worth naming."
        )
    )
    sprints: list[SprintResponse] = Field(
        description=(
            "Every sprint with work in it, newest first, whole project. The backlog is "
            "not among them: an item with no sprint is not planned into one, and a row "
            "for it would sit beside real sprints claiming to be one. Empty on a site "
            "that does not use sprints, which is a configuration rather than a failure."
        )
    )
    calendar: list[DayResponse] = Field(
        description=(
            "Effort logged per day over the last twelve weeks, oldest first, from the "
            "same worklogs as `effort_by_day`. Its own fixed span rather than the window, "
            "because it is a calendar grid and must not change shape when the window "
            "does. Days with nothing logged are omitted; a caller drawing the grid fills "
            "its own gaps."
        )
    )
    overdue: list[ItemResponse] = Field(
        description=(
            "Past its due date and not done, most overdue first. The whole project, not "
            "the window: an item overdue for a month and untouched since is the one most "
            "worth seeing, and a window filter would hide it."
        )
    )
    assignees: list[AssigneeResponse] = Field(
        description=(
            "One row per person, over the window's items. Busiest first. `estimated_seconds` "
            "and `spent_seconds` are Jira's lifetime totals on those issues, not effort "
            "inside the window — compare `effort_by_day` for that."
        )
    )
    epics: list[EpicResponse] = Field(
        description=(
            "Every epic in the project, including ones nothing moved under. `items` and "
            "`done` are the epic's whole size, which is what `percent` is drawn from; "
            "`moved` and `moved_done` are this window."
        )
    )
    effort_by_day: list[DayResponse] = Field(
        description=(
            "Logged effort per day, from worklogs and dated by the day the work was "
            "logged for — not from resolution dates, which a back-filled project moves."
        )
    )


@router.get("/{project}", response_model=DashboardResponse)
async def read_dashboard(
    project: str,
    user: Annotated[Principal, Depends(current_user)],
    days: int = Query(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS),
) -> DashboardResponse:
    """The numbers for one project.

    A project with no data is an empty dashboard, not a 404: a project set up but not yet
    synced is a normal state, and the page for it should say so rather than look broken.
    """
    if not await can_read_project(user, project):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your project")

    board = await get_dashboard(project, days=days)
    return DashboardResponse(
        project=board.project,
        since=board.since,
        until=board.until,
        percent=board.percent,
        all_totals=board.all_totals,
        totals=board.totals,
        priorities=board.priorities,
        kinds=[
            KindResponse(kind=k.kind, items=k.items, done=k.done) for k in board.kinds
        ],
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
        calendar=[
            DayResponse(day=d.day.isoformat(), seconds=d.seconds) for d in board.calendar
        ],
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
