"""Which projects have work in them, for the picker.

    GET  /projects       project keys this person may read

Behind `current_user`: it names the projects this deployment reads, which is not public.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from mycel.api.dependencies import current_user
from mycel.domains.dashboard import known_projects
from mycel.services.auth import Principal

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[str])
async def read_projects(user: Annotated[Principal, Depends(current_user)]) -> list[str]:
    """Projects with work in them, filtered to the ones this person may read.

    A list of keys and nothing else. A project has no attributes of its own in gold — its
    counts belong to a window, and asking for a window is what `/dashboard` is for.
    """
    return await known_projects(user)
