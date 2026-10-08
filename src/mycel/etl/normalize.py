"""Bronze to silver: a provider's payload becomes a row in the common shape."""

from datetime import UTC, datetime, time
from typing import Any

from mycel.core.config import team_zone
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow

JIRA = "jira"

#: Jira issue type names, lowered; an unknown type becomes `task`.
KINDS = {
    "epic": "epic",
    "story": "story",
    "task": "task",
    "subtask": "subtask",
    "sub-task": "subtask",
    "bug": "task",
}

#: Jira's `statusCategory.key` mapped to gold's CATEGORIES.
JIRA_CATEGORIES = {"new": "todo", "indeterminate": "doing", "done": "done"}


def from_jira_issue(payload: dict[str, Any], project: str) -> WorkItemRow | None:
    """One search result to a row, or None for a payload with no key or no fields."""
    key = payload.get("key")
    fields = payload.get("fields")
    if not key or not isinstance(fields, dict):
        return None

    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    created = _stamp(fields.get("created"))
    if created is None:
        return None

    return WorkItemRow(
        source=JIRA,
        project=project,
        issue_id=str(payload.get("id", "")),
        issue_key=str(key),
        kind=KINDS.get(str((fields.get("issuetype") or {}).get("name", "")).lower(), "task"),
        parent_key=(fields.get("parent") or {}).get("key"),
        title=str(fields.get("summary") or key),
        status=str(status.get("name") or "unknown"),
        status_category=JIRA_CATEGORIES.get(
            str((status.get("statusCategory") or {}).get("key", "")).lower(), "todo"
        ),
        priority=_priority(fields.get("priority")),
        **_sprint(fields.get("sprint")),
        assignee_account_id=assignee.get("accountId"),
        assignee_name=assignee.get("displayName"),
        original_estimate_seconds=_seconds(
            fields, "timeoriginalestimate", "originalEstimateSeconds"
        ),
        time_spent_seconds=_seconds(fields, "timespent", "timeSpentSeconds"),
        due_at=_due(fields.get("duedate")),
        created_at=created,
        resolved_at=_stamp(fields.get("resolutiondate")),
        labels=[str(label) for label in fields.get("labels") or []],
        updated_at=_stamp(fields.get("updated")) or created,
    )


def from_jira_worklog(payload: dict[str, Any], project: str) -> WorklogRow | None:
    """One worklog to a row; the bronze repository adds `issue_key` to the payload."""
    key = payload.get("issue_key")
    started = _stamp(payload.get("started"))
    if not key or started is None or not payload.get("id"):
        return None

    author = payload.get("author") or {}
    return WorklogRow(
        source=JIRA,
        project=project,
        worklog_id=str(payload["id"]),
        issue_key=str(key),
        author_account_id=author.get("accountId"),
        author_name=author.get("displayName"),
        time_spent_seconds=int(payload.get("timeSpentSeconds") or 0),
        started_at=started,
        comment=_text(payload.get("comment")),
    )


def _sprint(value: Any) -> dict[str, Any]:
    """The current sprint, the last in Jira's list; an empty list means backlog."""
    entries = [entry for entry in value or [] if isinstance(entry, dict)]
    if not entries:
        return {"sprint_id": None, "sprint_name": None, "sprint_state": None}

    current = entries[-1]
    raw = current.get("id")
    return {
        "sprint_id": int(raw) if isinstance(raw, int | str) and str(raw).isdigit() else None,
        "sprint_name": str(current["name"]) if current.get("name") else None,
        "sprint_state": str(current["state"]).lower() if current.get("state") else None,
    }


def _priority(value: Any) -> str | None:
    """The priority's name as the site spells it, or None when the field is hidden."""
    name = (value or {}).get("name") if isinstance(value, dict) else None
    return str(name) if name else None


def _stamp(value: Any) -> datetime | None:
    """Jira's timestamps: ISO 8601 with a `+0000` offset Python needs a colon in."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-2] + ":" + value[-2:] if value[-5] in "+-" and ":" not in value[-5:] else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _due(value: Any) -> datetime | None:
    """A bare due date, read as the end of that day in the team's zone, stored in UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        day = datetime.fromisoformat(value).date()
    except ValueError:
        return None
    return datetime.combine(day, time.max, tzinfo=team_zone()).astimezone(UTC)


def _seconds(fields: dict[str, Any], flat: str, nested: str) -> int | None:
    """A time field from the top level, or from `timetracking` when it is absent there."""
    value = fields.get(flat)
    if value is None:
        value = (fields.get("timetracking") or {}).get(nested)
    return int(value) if isinstance(value, int | float) else None


def _text(comment: Any) -> str | None:
    """Atlassian Document Format flattened to plain text."""
    if isinstance(comment, str):
        return comment or None
    if not isinstance(comment, dict):
        return None

    found: list[str] = []
    stack: list[Any] = [comment]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                found.append(node["text"])
            stack += node.get("content") or []
    return " ".join(reversed(found)).strip() or None
