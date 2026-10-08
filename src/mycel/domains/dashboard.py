"""The dashboard domain: one project, one window, one picture of it."""

from datetime import UTC, datetime, timedelta

from mycel.infra.postgres.session import session_scope
from mycel.services.auth import Principal
from mycel.services.dashboard import Dashboard, build_dashboard, list_projects
from mycel.services.permission import readable, require

#: The default window.
DEFAULT_DAYS = 7


async def get_dashboard(user: Principal, project: str, days: int = DEFAULT_DAYS) -> Dashboard:
    """Everything the dashboard shows, for the window ending now. `NotReadable` if not theirs."""
    await require(user, project)
    until = datetime.now(UTC)
    async with session_scope() as session:
        return await build_dashboard(session, project, until - timedelta(days=days), until)


async def known_projects(user: Principal) -> list[str]:
    """Which projects have data and this person may read, for the picker."""
    async with session_scope() as session:
        return await readable(user, await list_projects(session))
