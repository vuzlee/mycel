"""Can this person see this project.

The data is a team's own tracked work, so permission is checked before touching gold — not
after an answer has already been produced from it.

The rule is a row in `app.membership`: a grant exists, or it does not. The absent case is
the closed one on purpose — a table of denials would make a person nobody has recorded
anything about an administrator.

One function reads it, and every place that reads one project's data calls that function.
The rule lives here, so the day it grows a second clause it grows in one file.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.repositories.app import AppRepository, UserRow
from mycel.infra.postgres.session import session_scope
from mycel.services.auth import Principal


async def can_read_project(user: Principal, project: str) -> bool:
    """Whether this person may read this project's work."""
    return project in await readable_projects(user)


async def readable_projects(user: Principal) -> frozenset[str]:
    """Everything this person may read, in one query.

    Filtering a list of projects one `can_read_project` at a time is a query per project.
    Callers with a list ask this once instead.
    """
    async with session_scope() as session:
        return await AppRepository(session).projects_for(user.id)


async def members_of(project: str) -> list[UserRow]:
    """Everyone granted this project, for the screen that manages them. The caller checks
    it may see the project first — this function answers, it does not decide."""
    async with session_scope() as session:
        return await AppRepository(session).members_of(project)


async def grant(session: AsyncSession, user_id: int, project: str) -> None:
    """Give someone a project. `api/routes/members.py` is the way in; a shell still works
    and is what a deployment with nobody granted anything has to start from."""
    await AppRepository(session).grant_project(user_id, project)


async def revoke(session: AsyncSession, user_id: int, project: str) -> None:
    """Take a project back. Sessions are untouched — this is about data, not about login."""
    await AppRepository(session).revoke_project(user_id, project)
