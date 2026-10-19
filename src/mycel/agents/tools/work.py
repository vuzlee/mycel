"""Tools for the questions asked most: one call returns what several `run_sql` rounds did.

Each runs a fixed query through `query.read`, so the asker's project scope and the
read-only role apply exactly as they do to model-written SQL.
"""

from typing import Literal

from pydantic_ai import FunctionToolset, RunContext

from mycel.agents.core import charts
from mycel.agents.core.chips import opens
from mycel.agents.core.deps import MycelDeps
from mycel.agents.tools.query import final, read_rows
from mycel.core.chips import Chip
from mycel.events.event import CHART, AgentEvent

#: Tools whose rows are already the answer; the analyst stops querying after one.
READY_READS = frozenset({"hours_by_person", "late_items", "open_epics"})

Period = Literal["this_week", "last_week", "this_month", "last_month"]

#: Start and end of each period, in the database's clock.
_PERIODS: dict[str, tuple[str, str]] = {
    "this_week": ("date_trunc('week', now())", "now()"),
    "last_week": ("date_trunc('week', now()) - interval '1 week'", "date_trunc('week', now())"),
    "this_month": ("date_trunc('month', now())", "now()"),
    "last_month": (
        "date_trunc('month', now()) - interval '1 month'",
        "date_trunc('month', now())",
    ),
}

_HOURS_BY_PERSON = """
WITH logged AS (
    SELECT w.author_name, w.issue_key, i.title, SUM(w.time_spent_seconds) / 3600.0 AS hours
    FROM gold.worklog w
    LEFT JOIN gold.work_item i ON i.issue_key = w.issue_key
    WHERE w.started_at >= {start} AND w.started_at < {end}
    GROUP BY w.author_name, w.issue_key, i.title
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY author_name ORDER BY hours DESC) AS place,
           SUM(hours) OVER (PARTITION BY author_name) AS person_hours,
           COUNT(*) OVER (PARTITION BY author_name) AS person_issues
    FROM logged
)
SELECT author_name, round(person_hours, 2) AS total_hours, person_issues AS issues,
       issue_key, title, round(hours, 2) AS hours
FROM ranked
WHERE place <= :top_issues
ORDER BY person_hours DESC, hours DESC
LIMIT 60
"""

_LATE = """
SELECT issue_key, title, kind, status, assignee_name, due_at::date AS due,
       (now()::date - due_at::date) AS days_late
FROM gold.work_item
WHERE status_category <> 'done' AND due_at < now()
ORDER BY due_at
LIMIT 100
"""

_OPEN_EPICS = """
SELECT e.issue_key, e.title, e.status,
       COUNT(c.issue_key) AS children,
       COUNT(c.issue_key) FILTER (WHERE c.status_category <> 'done') AS open_children,
       round(COALESCE(SUM(c.original_estimate_seconds), 0) / 3600.0, 1) AS estimate_hours,
       round(COALESCE(SUM(c.time_spent_seconds), 0) / 3600.0, 1) AS spent_hours,
       round(COALESCE(SUM(c.original_estimate_seconds)
             FILTER (WHERE c.status_category <> 'done'), 0) / 3600.0, 1) AS open_estimate_hours
FROM gold.work_item e
LEFT JOIN gold.work_item c ON c.parent_key = e.issue_key
WHERE e.kind = 'epic' AND e.status_category <> 'done'
GROUP BY e.issue_key, e.title, e.status
ORDER BY open_children DESC
LIMIT 100
"""


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset(metadata=opens(Chip.JIRA))

    @toolset.tool(name="hours_by_person")
    async def _hours_by_person(
        ctx: RunContext[MycelDeps], period: Period = "this_month", top_issues: int = 5
    ) -> str:
        """Hours logged per person in a period, most first, with their top issues by title.

        Use for "who logged the most", "what did X work on", "hours this week".

        Args:
            period: this_week, last_week, this_month or last_month.
            top_issues: How many of each person's issues to list, by hours (1-20).
        """
        start, end = _PERIODS[period]
        query = _HOURS_BY_PERSON.format(start=start, end=end)
        columns, rows = await read_rows(
            ctx.deps, query, {"top_issues": max(1, min(top_issues, 20))}
        )
        people: dict[str, float] = {}
        for row in rows:
            people.setdefault(str(row[0]), float(row[1]))
        when = period.replace("_", " ")
        if len(people) > 1:
            chart = charts.build("bar", f"Hours per person, {when}", "h", list(people.items()))
        else:
            # One person: the split worth seeing is across their issues.
            issues = [(f"{row[3]} {row[4] or ''}".strip(), float(row[5])) for row in rows]
            chart = charts.build("bar", f"Hours per issue, {when}", "h", issues)
        await _draw(ctx, chart)
        return final(columns, rows)

    @toolset.tool(name="late_items")
    async def _late_items(ctx: RunContext[MycelDeps]) -> str:
        """Open items past their due date, oldest first, with who has them.

        Use for "what is late", "what is overdue", "who is behind".
        """
        columns, rows = await read_rows(ctx.deps, _LATE)
        points = [(f"{row[0]} {row[1]}", float(row[6])) for row in rows]
        await _draw(ctx, charts.build("bar", "Days late", "d", points))
        return final(columns, rows)

    @toolset.tool(name="open_epics")
    async def _open_epics(ctx: RunContext[MycelDeps]) -> str:
        """Open epics with their children: how many are open, estimate, spent, open estimate.

        Use for "which epics are open", "how much work is left".
        """
        columns, rows = await read_rows(ctx.deps, _OPEN_EPICS)
        points = [(f"{row[0]} {row[1]}", float(row[7])) for row in rows]
        await _draw(ctx, charts.build("bar", "Open estimate per epic", "h", points))
        return final(columns, rows)

    return toolset


async def _draw(ctx: RunContext[MycelDeps], chart: dict[str, object] | None) -> None:
    """Send the chart straight to the page: drawn from rows, it never passes a model."""
    if chart is None:
        return
    await ctx.deps.events.publish(
        AgentEvent(agent="chart", type=CHART, payload={"chart": chart}, parent_tool_call_id=None)
    )
