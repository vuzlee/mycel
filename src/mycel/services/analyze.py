"""Hand data to agents/ for analysis, get structured results back.

The boundary between a query result and a prompt. `gather.py` reads the database, this
turns what it read into the text an agent is given and runs the agent on it — so the
agent module stays a prompt and a schema, and nothing under `agents/` ever imports a
service.

If the model returns the wrong format, `runner.run` retries it here rather than letting
bad data move on.
"""

from mycel.agents.agent.summariser import Summariser
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.schemas import ProgressSummary
from mycel.infra.postgres.repositories.gold import SECONDS_PER_DAY, WorkItemRow
from mycel.services.gather import ProgressWindow

#: Date format in the prompt. ISO with a space: unambiguous to a model, and short enough
#: that a few hundred rows do not spend the context on timestamps.
STAMP = "%Y-%m-%d"


async def summarise_progress(
    window: ProgressWindow, deps: MycelDeps, settings: AgentSettings | None = None
) -> ProgressSummary:
    """Summarise one window. Every fact the model gets is in `render(window)`."""
    cfg = settings or AgentSettings.from_config(Summariser.name)
    return await runner.run(Summariser.build(cfg), render(window), deps, cfg)


def render(window: ProgressWindow) -> str:
    """The window as the prompt the summariser reads.

    Plain lines rather than JSON: the model copies people's own words out of this, and a
    quoted-and-escaped blob is one more thing between it and them.

    Seconds become days here and nowhere else. Gold stores what Jira stores; a unit a
    person reads is a display decision, and this is the display.
    """
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
    """One work item on one line, as named fields the output schema also names.

    `key=... title=...` rather than a sentence with the parts in a fixed order. The model
    copies these into a row of the same names, and a label it can match beats a position
    it has to count — the first version wrote the kind immediately before the title and
    got back titles reading "story: 003 — API skeleton".

    A field the row does not carry is omitted rather than written as zero. An estimate of
    zero reads as one that was met; a missing estimate is a ticket nobody sized.
    """
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
    return f"{seconds / SECONDS_PER_DAY:.1f}d"
