"""What a row must satisfy before it is allowed into gold.

Pure functions over rows already in memory. They run between the transform and the write,
so a bad row is refused at the boundary rather than found later by someone reading a
report.

Each check returns a reason, or None when the row is fine. A reason is a sentence, because
it ends up in a log line that someone has to act on.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from mycel.core.exceptions import MycelError
from mycel.etl.normalise import CATEGORIES
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow

#: How far ahead of now a *timestamp about the past* may claim to be. Clock skew between a
#: provider and this machine is normal and small; a day is not skew, it is a parsing bug.
#: Due dates are exempt — being in the future is the entire point of one.
FUTURE_TOLERANCE = timedelta(minutes=5)

VALID_CATEGORIES = frozenset(CATEGORIES.values())


class CheckFailed(MycelError):
    """A row did not satisfy a check, so nothing was written to the layer above."""


def check_item(row: WorkItemRow) -> str | None:
    """Everything one work item must be true about itself."""
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
    """Everything one logged entry must be true about itself.

    A back-dated `started` is allowed and is why this source was chosen; a *future* one is
    not, because nobody logs effort they have not spent yet.
    """
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
    """Every reason found, across every row. All of them, not the first.

    One bad row usually means a class of bad rows, and fixing them one exception per run
    is the slowest possible way to find that out.
    """
    return [
        f"{row.source}:{row.issue_key} — {reason}"
        for row in rows
        if (reason := check_item(row)) is not None
    ]


def check_worklogs(rows: Sequence[WorklogRow]) -> list[str]:
    """Every reason found, across every logged entry."""
    return [
        f"{row.source}:{row.issue_key}:{row.worklog_id} — {reason}"
        for row in rows
        if (reason := check_worklog(row)) is not None
    ]
