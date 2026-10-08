"""Who may read which project, asked of Jira on each person's own token."""

import httpx2

from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.session import session_scope
from mycel.services import jira_oauth
from mycel.sources import jira

log = get_logger(__name__)


async def refresh(user_id: int) -> frozenset[str]:
    """Ask Jira which projects this person may browse, and make that their access."""
    try:
        token, cloud_id = await jira_oauth.token_for(user_id)
        projects = frozenset(await jira.browsable_projects(jira.Auth(token, cloud_id)))
    except (MycelError, httpx2.HTTPError):
        log.warning(
            "could not read jira access; clearing it", extra={"user_id": user_id}, exc_info=True
        )
        projects = frozenset()
    async with session_scope() as session:
        await AccountRepository(session).replace_projects(user_id, projects)
    return projects


async def refresh_everyone() -> int:
    """Refresh every connected person. Returns how many were refreshed."""
    async with session_scope() as session:
        users = await AccountRepository(session).jira_connected_users()
    for user_id in users:
        await refresh(user_id)
    return len(users)
