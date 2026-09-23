"""What a project's window looks like, counted rather than written.

Batch 027 deleted `/app/dashboard` and 035 deleted `get_dashboard` with it. What is left
is what still has callers: `known_projects`, for `/projects`, and `DEFAULT_DAYS`, which is
what the `summariser` tool falls back to when the orchestrator names no window.

No queue, no agent, no model: this answers inside the request, in milliseconds, which is
exactly the speed batch 027 traded away on purpose. See its note for why.
"""

from mycel.infra.postgres.session import session_scope
from mycel.services.dashboard import list_projects

#: The default window. A week covers a team that works on weekdays and rests at the
#: weekend; a shorter one makes a normal Monday look like a dead project.
DEFAULT_DAYS = 7


async def known_projects() -> list[str]:
    """Which projects have data."""
    async with session_scope() as session:
        return await list_projects(session)
