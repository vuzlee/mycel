"""What a project's window looks like, counted rather than written.

Batch 027 deleted `/app/dashboard` and the route under it, so `get_dashboard` has no
caller left. It is kept rather than deleted because the queries under it are a verified
read of gold, and `DEFAULT_DAYS` here is what the `summariser` tool falls back to when the
orchestrator names no window. `known_projects` is still called, by `/projects`.

No queue, no agent, no model: this answers inside the request, in milliseconds, which is
exactly the speed batch 027 traded away on purpose. See its note for why.
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
    """Which projects have data."""
    async with session_scope() as session:
        return await list_projects(session)
