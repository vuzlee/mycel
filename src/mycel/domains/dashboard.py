"""The dashboard domain: one project, one window, one picture of it.

One step — no queue, no agent, no model. A dashboard is a handful of counting queries and
answers in milliseconds, so it runs inside the request rather than being handed to a
worker. That is also what makes it the cheapest feature in the system.

Batch 027 deleted it and batch 040 brought it back, which is worth saying rather than
hiding. 027's reasoning was that one way in is better than three, and that holds for
*asking questions*: a summary and a progress narrative are the analyst's job, and a screen
of them was a second interface to the same answers. It does not hold for *looking*. The
questions a board answers — what is late, who is loaded, what moved — are asked over and
over, at a glance, and paying a model round-trip to re-derive a count that SQL already has
is the wrong trade. The analyst stays for everything a fixed screen cannot ask.
"""

from datetime import UTC, datetime, timedelta

from mycel.infra.postgres.session import session_scope
from mycel.services.dashboard import Dashboard, build_dashboard, list_projects

#: The default window. A week covers a team that works on weekdays and rests at the
#: weekend; a shorter one makes a normal Monday look like a dead project.
DEFAULT_DAYS = 7


async def get_dashboard(project: str, days: int = DEFAULT_DAYS) -> Dashboard:
    """Everything the dashboard shows, for the window ending now."""
    until = datetime.now(UTC)
    async with session_scope() as session:
        return await build_dashboard(session, project, until - timedelta(days=days), until)


async def known_projects() -> list[str]:
    """Which projects have data, for the picker."""
    async with session_scope() as session:
        return await list_projects(session)
