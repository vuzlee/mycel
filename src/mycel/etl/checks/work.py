"""Pure checks a row must pass before it is written to gold."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from mycel.core.exceptions import MycelError
from mycel.etl.normalise import CATEGORIES
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow

#: How far a past timestamp may sit ahead of now (clock skew); due dates are exempt.
FUTURE_TOLERANCE = timedelta(minutes=5)

VALID_CATEGORIES = frozenset(CATEGORIES.values())


class CheckFailed(MycelError):
    """A row did not satisfy a check, so nothing was written to the layer above."""


def check_item(row: WorkItemRow) -> str | None:
    if not row.issue_key.strip():
        return "issue_key is empty"
    if not row.title.strip():
        return "title is empty"
    if row.status_category not in VALID_CATEGORIES:
        return f"status_category {row.status_category!r} is not one of {sorted(VALID_CATEGORIES)}"
    if row.parent_key == row.issue_key:
        return "parent_key points at the item itself"
    if row.created_at.tzinfo is None:
        return "created_at has no timezone"
    if row.due_at is not None and row.due_at.tzinfo is None:
        return "due_at has no timezone"
    if row.created_at > datetime.now(UTC) + FUTURE_TOLERANCE:
        return f"created_at is in the future: {row.created_at.isoformat()}"
    if row.resolved_at is not None and row.resolved_at < row.created_at:
        return "resolved_at is before created_at"
    return None


def check_worklog(row: WorklogRow) -> str | None:
    """A back-dated `started` is allowed; a future one is not."""
    if not row.issue_key.strip():
        return "issue_key is empty"
    if row.time_spent_seconds <= 0:
        return f"time_spent_seconds is {row.time_spent_seconds}"
    if row.started_at.tzinfo is None:
        return "started_at has no timezone"
    if row.started_at > datetime.now(UTC) + FUTURE_TOLERANCE:
        return f"started_at is in the future: {row.started_at.isoformat()}"
    return None


def check_items(rows: Sequence[WorkItemRow]) -> list[str]:
    """Every reason across every row, not just the first."""
    return [
        f"{row.source}:{row.issue_key} — {reason}"
        for row in rows
        if (reason := check_item(row)) is not None
    ]


def check_worklogs(rows: Sequence[WorklogRow]) -> list[str]:
    return [
        f"{row.source}:{row.issue_key}:{row.worklog_id} — {reason}"
        for row in rows
        if (reason := check_worklog(row)) is not None
    ]
