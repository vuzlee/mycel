"""Who may read a project, and the two calls that change it.

    GET     /projects/{project}/members        who has been granted it
    PUT     /projects/{project}/members/{email}   grant it
    DELETE  /projects/{project}/members/{email}   take it back

**You may grant a project you can read.** There is no separate administrator role, because
one would need a table, a way to become one, and a first one to bootstrap — and the answer
to all three would be the shell this endpoint exists to replace. Migration 0007 gave every
account that existed at upgrade time every project, so a deployment starts with people who
can invite, and a person invited into one project can invite into that one and no other.

The address is the identifier, not a user id: the person doing this knows who they work
with by email and has no way to learn an id.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.api.dependencies import current_user, get_db
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.app import AppRepository
from mycel.services.auth import Principal
from mycel.services.permission import grant, members_of, readable_projects, revoke

router = APIRouter(prefix="/projects", tags=["members"])

log = get_logger(__name__)


class Member(BaseModel):
    """One person who may read the project."""

    id: int
    email: str


@router.get("/{project}/members", response_model=list[Member])
async def read_members(
    project: str,
    user: Annotated[Principal, Depends(current_user)],
) -> list[Member]:
    """Who may read this project. Only visible to someone who may read it themselves."""
    await _must_read(user, project)
    return [Member(id=m.id, email=m.email) for m in await members_of(project)]


@router.put("/{project}/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def add_member(
    project: str,
    email: str,
    user: Annotated[Principal, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Grant the project. Granting twice is not an error — the end state is what was asked
    for, which is what makes this a `PUT`."""
    await _must_read(user, project)
    target = await _lookup(session, email)
    await grant(session, target, project)
    log.info("project granted", extra={"project": project, "by": user.id, "to": target})


@router.delete("/{project}/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project: str,
    email: str,
    user: Annotated[Principal, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Take the project back. Revoking your own last project is allowed and locks you out
    of it — the alternative is a rule that cannot be explained in one line."""
    await _must_read(user, project)
    target = await _lookup(session, email)
    await revoke(session, target, project)
    log.info("project revoked", extra={"project": project, "by": user.id, "from": target})


async def _must_read(user: Principal, project: str) -> None:
    """404, not 403: someone who cannot read a project should not learn it exists."""
    if project not in await readable_projects(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such project")


async def _lookup(session: AsyncSession, email: str) -> int:
    """The account behind an address. There is no inviting someone who has not signed up:
    an account that exists before its owner does is an account nobody controls."""
    target = await AppRepository(session).user_by_email(email.strip().lower())
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no account with that address")
    return target.id
