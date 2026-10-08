"""Which projects have work in them, for the picker."""

from fastapi import APIRouter

from mycel.api.dependencies import CurrentUser
from mycel.services.dashboards import known_projects

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[str])
async def list_readable_projects(user: CurrentUser) -> list[str]:
    """Projects with work in them, filtered to the ones this person may read."""
    return await known_projects(user)
