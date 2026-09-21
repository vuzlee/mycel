"""Read one project's progress: the first thing in this system a person can just look at.

Synchronous, unlike `/reports`. A report is minutes of agent work and gets a job id; a
dashboard is a handful of SQL queries, so it answers in the request and needs no receipt.

    GET  /dashboard/{project}        the numbers, as JSON
    GET  /dashboard/{project}/page   the old standalone page, now a redirect into the app
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from mycel.api.dependencies import current_user
from mycel.core.logging import get_logger
from mycel.domains.dashboard import DEFAULT_DAYS, get_dashboard
from mycel.infra.postgres.repositories.gold import WorkItemRow
from mycel.services.auth import Principal
from mycel.services.permission import may_read_project

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

#: Longest window a caller may ask for. Not a performance limit — the counting is in SQL —
#: but a year of history on one screen is not a dashboard, it is an export.
MAX_DAYS = 90

log = get_logger(__name__)


class ItemResponse(BaseModel):
    """One work item, as a page lists it."""

    issue_key: str
    kind: str
    title: str
    status: str
    status_category: str
    assignee_name: str | None = None
    original_estimate_seconds: int | None = None
    time_spent_seconds: int | None = None
    due_at: datetime | None = None


class AssigneeResponse(BaseModel):
    """One person's row, summed over the window's items.

    `gap_seconds` is spent minus estimated: positive means over the estimate. Seconds
    throughout — man-days are a display decision and belong to whatever renders this.

    The window picks *which* issues are summed, not which hours: these are Jira's
    lifetime totals on each issue. `effort_by_day` counts worklogs dated inside the
    window instead, so the two are not two views of one number.
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


class DayResponse(BaseModel):
    """Seconds logged on one day, across everybody."""

    day: str
    seconds: int


class DashboardResponse(BaseModel):
    """What one project has been doing, in the window asked for.

    Every list here is scoped to `since`..`until` except `overdue`, which is whole-project.
    That difference is deliberate and each field says so: a caller that assumes one scope
    for all of them reports the wrong thing.
    """

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
            "`moved` and `moved_done` are this window. The epic itself is counted in "
            "`totals` and `assignees` like any other issue, but never in its own `items`."
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

    A project with no data is an empty dashboard, not a 404: a project that has been set
    up but not yet synced is a normal state, and the page for it should say so rather than
    look broken.
    """
    if not await may_read_project(user, project):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your project")

    board = await get_dashboard(project, days=days)
    return DashboardResponse(
        project=board.project,
        since=board.since,
        until=board.until,
        percent=board.percent,
        all_totals=board.all_totals,
        totals=board.totals,
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


@router.get("/{project}/page", include_in_schema=False)
async def dashboard_page(
    project: str,
    days: int = Query(default=DEFAULT_DAYS),
) -> RedirectResponse:
    """The page moved into the app in batch 014, and this keeps the old link working.

    It used to serve a standalone HTML file in its own palette and its own font stack — a
    second design system for one screen. The screen is now `/app/dashboard`, and a URL
    somebody bookmarked or a script printed should still land on it rather than 404.
    """
    return RedirectResponse(f"/app/dashboard?project={project}&days={days}")


def _item(row: WorkItemRow) -> ItemResponse:
    """A gold row as the page sees it. Seconds stay seconds; days are the UI's decision."""
    return ItemResponse(
        issue_key=row.issue_key,
        kind=row.kind,
        title=row.title,
        status=row.status,
        status_category=row.status_category,
        assignee_name=row.assignee_name,
        original_estimate_seconds=row.original_estimate_seconds,
        time_spent_seconds=row.time_spent_seconds,
        due_at=row.due_at,
    )
