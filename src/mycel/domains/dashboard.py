"""The dashboard domain: one project, one window, one picture of it.

One step today — no queue, no agent, no model. A dashboard is a handful of queries, and it
answers in milliseconds, so it runs inside the request rather than being handed to a
worker. That is also what makes it the cheapest feature in the system.
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
    """Which projects have data, for the picker on the dashboard and reports pages."""
    async with session_scope() as session:
        return await list_projects(session)
