"""Can this person see this project."""

from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.session import session_scope
from mycel.services.auth import Principal


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


async def readable(user: Principal | None, projects: list[str]) -> list[str]:
    """`projects`, keeping only those this person may read, in the order given."""
    if user is None:
        return []
    allowed = await readable_projects(user)
    return [p for p in projects if p in allowed]
