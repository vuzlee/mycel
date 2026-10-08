"""Turn a query result into the text an agent is given."""

from mycel.infra.postgres.repositories.gold import WORKDAY_SECONDS, WorkItemRow
from mycel.services.gather import ProgressWindow

#: Date format in the prompt.
STAMP = "%Y-%m-%d"


def render(window: ProgressWindow) -> str:
    """The window as the prompt the summariser reads."""
    period = f"{window.since.strftime(STAMP)} to {window.until.strftime(STAMP)}"
    lines = [f"Project {window.project}, {period}", ""]

    if window.dropped:
        lines += [
            f"NOTE: {window.dropped} older items were dropped to fit. This summary covers "
            "the most recent ones only, and must say so.",
            "",
        ]

    totals = ", ".join(f"{category}: {n}" for category, n in window.totals.items())
    lines += [f"Totals — {totals}", ""]

    if window.is_empty:
        lines.append("Nothing moved in this window.")
        return "\n".join(lines)

    lines += _hierarchy(window)
    lines += _overdue(window)
    lines += _load(window)
    lines += _effort(window)
    return "\n".join(lines)


def _hierarchy(window: ProgressWindow) -> list[str]:
    """Work grouped under the epic it belongs to, which is the level a plan is read at."""
    lines = ["Work, by epic:"]
    for epic, children in window.by_epic.items():
        title = window.epic_titles.get(epic, "(epic not in this window)")
        lines.append(f"  {epic} — {title}")
        lines += [f"    {_item(child)}" for child in children] or ["    (nothing moved under it)"]
    if window.orphans:
        lines += ["  (no epic)"] + [f"    {_item(item)}" for item in window.orphans]
    return [*lines, ""]


def _overdue(window: ProgressWindow) -> list[str]:
    """Past due and not done, most overdue first. Empty is worth stating."""
    if not window.overdue:
        return ["Nothing is past its due date.", ""]
    lines = ["Past due and not done, most overdue first:"]
    lines += [f"  {_item(item)}" for item in window.overdue]
    return [*lines, ""]


def _load(window: ProgressWindow) -> list[str]:
    """Per person, in days, with the gap already subtracted."""
    if not window.by_assignee:
        return []
    lines = [
        "Per person — items, done, estimated vs spent (days). These are Jira's lifetime "
        "totals on the issues touched in this window, not effort spent inside it:"
    ]
    for person in window.by_assignee:
        estimated = _days(person.estimated_seconds)
        spent = _days(person.spent_seconds)
        gap = _days(person.gap_seconds)
        over = "over" if person.gap_seconds > 0 else "under"
        lines.append(
            f"  {person.name} — {person.items} items, {person.done} done, "
            f"estimated {estimated}, spent {spent} ({gap} {over})"
        )
    return [*lines, ""]


def _effort(window: ProgressWindow) -> list[str]:
    """Hours logged per day. The one time series that survives a back-filled project."""
    if not window.effort_by_day:
        return []
    days = ", ".join(f"{d.day.isoformat()}: {d.seconds / 3600:.1f}h" for d in window.effort_by_day)
    return [
        f"Effort logged inside this window, per day — {days}",
        "(Worklogs dated in the window. Will not add up to the per-person spent above.)",
        "",
    ]


def _item(row: WorkItemRow) -> str:
    """One work item on one line, as named fields the output schema also names."""
    parts = [
        f"key={row.issue_key}",
        f"status={row.status}",
        f"kind={row.kind}",
        f"title={row.title}",
    ]
    if row.assignee_name:
        parts.append(f"who={row.assignee_name}")
    if row.original_estimate_seconds:
        parts.append(f"estimated={_days(row.original_estimate_seconds)}")
    if row.time_spent_seconds:
        parts.append(f"spent={_days(row.time_spent_seconds)}")
    if row.due_at:
        parts.append(f"due={row.due_at.strftime(STAMP)}")
    return "  ".join(parts)


def _days(seconds: int) -> str:
    """Seconds as man-days, at Jira's own eight-hour working day."""
    return f"{seconds / WORKDAY_SECONDS:.1f}d"
