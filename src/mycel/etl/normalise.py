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
from zoneinfo import ZoneInfo

from mycel.core.config import get_settings
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
        priority=_priority(fields.get("priority")),
        **_sprint(fields.get(get_settings().jira_sprint_field)),
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


def _sprint(value: Any) -> dict[str, Any]:
    """Jira's sprint array, reduced to the sprint the item is in now.

    The field is a list because an issue rolled over from one sprint to the next lists
    both, oldest first. The last is the one it is in, and the only one a board should
    count — an issue present in three sprints at once makes every total larger than the
    board it describes.

    An empty list and a missing field are the same answer: this item is in the backlog.
    """
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
    """Jira's priority object, reduced to its name.

    The site's own word, not a rank: one team's "Blocker" is another's "Highest", and a
    number here would have to invent a mapping that only the UI could undo. None when the
    field is hidden on the site, which is a normal configuration rather than missing data.
    """
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
    """A due date is a bare `YYYY-MM-DD`: no time, no zone.

    Read as the end of that day rather than the start, so an item due today is not already
    late at nine in the morning — and the end of the day in the *team's* zone, not UTC. A
    UTC+7 team reading it as UTC gets seven hours in which overdue work still counts as on
    time. Stored in UTC either way; only the moment the day ends moves.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        day = datetime.fromisoformat(value).date()
    except ValueError:
        return None
    return datetime.combine(day, time.max, tzinfo=_zone()).astimezone(UTC)


def _zone() -> ZoneInfo:
    """The team's zone, falling back to UTC if the name is not one the system knows."""
    try:
        return ZoneInfo(get_settings().timezone)
    except Exception:
        return ZoneInfo("UTC")


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
