"""Which projects have work in them, for the picker."""

from typing import Annotated

from fastapi import APIRouter, Depends

from mycel.api.dependencies import current_user
from mycel.domains.dashboard import known_projects
from mycel.services.auth import Principal

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[str])
async def read_projects(user: Annotated[Principal, Depends(current_user)]) -> list[str]:
    """Projects with work in them, filtered to the ones this person may read."""
    return await known_projects(user)
