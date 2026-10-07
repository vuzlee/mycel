"""Who may read which project, asked of Jira on each person's own token.

Jira already knows who may browse what; a second list kept here by hand only drifts from
it. So `app.membership` is a copy, written by nothing but this file: on connect, and for
everyone connected after each sync. A person removed from a project in Jira loses it here
within one sync.

A person whose token no longer works keeps nothing. Failing closed is the only safe
reading of "we could not ask". A bug is not "could not ask": it raises.
"""

import httpx

from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.app import AppRepository
from mycel.infra.postgres.session import session_scope
from mycel.services import jira_oauth
from mycel.sources import jira

log = get_logger(__name__)


async def refresh(user_id: int) -> frozenset[str]:
    """Ask Jira which projects this person may browse, and make that their access."""
    try:
        token, cloud_id = await jira_oauth.token_for(user_id)
        projects = frozenset(await jira.browsable_projects(jira.Auth(token, cloud_id)))
    except (MycelError, httpx.HTTPError):
        log.warning(
            "could not read jira access; clearing it", extra={"user_id": user_id}, exc_info=True
        )
        projects = frozenset()
    async with session_scope() as session:
        await AppRepository(session).replace_projects(user_id, projects)
    return projects


async def refresh_everyone() -> int:
    """Refresh every connected person. Returns how many were refreshed."""
    async with session_scope() as session:
        users = await AppRepository(session).jira_connected_users()
    for user_id in users:
        await refresh(user_id)
    return len(users)
