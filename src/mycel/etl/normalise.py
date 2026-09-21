"""Bronze to silver: a provider's issue payload becomes a row in the common shape.

The first of two hops. This one unwraps the envelope and lands in silver;
`etl/promote.py` takes silver to gold.

Normalising only. Nothing is judged or dropped for its content — an issue nobody has
touched is still tracked work, and silver is what remembers it exists.

One function per source, because only the unwrapping differs; what comes out is always a
`WorkItemRow` or a `WorklogRow`. Field names follow the source wherever the source has
one, so a column downstream can be traced back to a payload in bronze without a
translation table in someone's head.
"""

from datetime import UTC, datetime, time
from typing import Any

from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow

JIRA = "jira"

#: Jira's issue type names, lowered, mapped to the four levels this system knows. An
#: unrecognised type becomes `task`, which is the only honest guess: it is a unit of work
#: that is not an epic and has no children we were told about.
KINDS = {
    "epic": "epic",
    "story": "story",
    "task": "task",
    "subtask": "subtask",
    "sub-task": "subtask",
    "bug": "task",
}

#: Jira's own `statusCategory.key`. `new` and `indeterminate` are the API's names for what
#: every board calls to-do and in-progress; renaming them here is the one place this
#: module does not keep the source's word, because two of the three are unreadable.
CATEGORIES = {"new": "todo", "indeterminate": "doing", "done": "done"}


def from_jira_issue(payload: dict[str, Any], project: str) -> WorkItemRow | None:
    """One search result in, at most one row out.

    Returns None for a payload with no key or no fields — a shape Jira does not produce
    but a replay of half-written bronze can.
    """
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
        status_category=CATEGORIES.get(
            str((status.get("statusCategory") or {}).get("key", "")).lower(), "todo"
        ),
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
    """One worklog entry in, at most one row out.

    `issue_key` is put on the payload by the bronze repository: Jira serves worklogs from
    a per-issue URL and does not repeat the key inside the entry.
    """
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
    """A due date is a bare `YYYY-MM-DD`: no time, no zone.

    Read as the end of that day in UTC rather than the start, so an item due today is not
    already late at nine in the morning.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.combine(datetime.fromisoformat(value).date(), time.max, tzinfo=UTC)
    except ValueError:
        return None


def _seconds(fields: dict[str, Any], flat: str, nested: str) -> int | None:
    """Jira reports time twice: a top-level field and inside `timetracking`.

    They can disagree — the top-level one is absent on a site where the field is hidden
    from the screen while `timetracking` still carries it — so both are consulted and the
    first that answers wins.
    """
    value = fields.get(flat)
    if value is None:
        value = (fields.get("timetracking") or {}).get(nested)
    return int(value) if isinstance(value, int | float) else None


def _text(comment: Any) -> str | None:
    """A worklog comment is Atlassian Document Format: a tree with the text at the leaves.

    Flattened to a sentence rather than stored as a document, because the only consumer is
    a prompt and a model reads prose better than it reads a node tree.
    """
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
