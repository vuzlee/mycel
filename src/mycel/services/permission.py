"""Can this person see this project."""

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.principal import Principal
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.session import session_scope


async def can_read_project(user: Principal, project: str) -> bool:
    """Whether this person may read this project's work."""
    return project in await readable_projects(user)


async def readable_projects(user: Principal) -> frozenset[str]:
    """Everything this person may read, in one query."""
    async with session_scope() as session:
        return await AccountRepository(session).projects_for(user.id)


class NotReadable(Exception):
    """This person may not read this project. Worded the same whether it exists or not."""


async def require(user: Principal | None, project: str) -> None:
    """Raise `NotReadable` unless this person may read `project`. No person, no access."""
    if user is None or not await can_read_project(user, project):
        raise NotReadable(f"project {project} does not exist or you do not have access to it")


async def readable(
    user: Principal | None, projects: list[str], session: AsyncSession | None = None
) -> list[str]:
    """`projects`, keeping only those this person may read, in the order given.

    Pass the caller's `session` when one is open: a second session inside it holds a second
    pool connection, and a pool full of outer sessions then waits on itself.
    """
    if user is None:
        return []
    if session is None:
        allowed = await readable_projects(user)
    else:
        allowed = await AccountRepository(session).projects_for(user.id)
    return [p for p in projects if p in allowed]
