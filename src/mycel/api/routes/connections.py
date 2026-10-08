"""Connected accounts: Google and Jira, each on the person's own consent."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from mycel.api.dependencies import current_user
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.services import access, auth, google_oauth, jira_oauth
from mycel.services.permission import readable_projects

router = APIRouter(prefix="/auth", tags=["connections"])

log = get_logger(__name__)


class _Connected(Protocol):
    """Any connected-account row: what `_finish_connect` reads off it."""

    @property
    def user_id(self) -> int: ...


class GoogleStatus(BaseModel):
    """Whether a Google account is attached, and which one."""

    configured: bool
    email: str | None = None
    connected_at: str | None = None


@router.get("/google", response_model=GoogleStatus)
async def google_status(user: Annotated[auth.Principal, Depends(current_user)]) -> GoogleStatus:
    """Which Google account this person has connected, if any."""
    if not google_oauth.configured():
        return GoogleStatus(configured=False)
    row = await google_oauth.connected(user.id)
    if row is None:
        return GoogleStatus(configured=True)
    return GoogleStatus(configured=True, email=row.email, connected_at=row.connected_at.isoformat())


@router.get("/google/start")
async def google_start(
    user: Annotated[auth.Principal, Depends(current_user)],
) -> RedirectResponse:
    """Send the browser to Google's consent screen."""
    if not google_oauth.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "this deployment has no Google client"
        )
    return RedirectResponse(await google_oauth.consent_url(user.id))


@router.get("/google/callback")
async def google_callback(
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Where Google sends the browser back. Connects the account, then returns to the app."""
    return await _finish_connect("google", google_oauth.connect, code, state, error)


@router.delete("/google", status_code=status.HTTP_204_NO_CONTENT)
async def google_disconnect(user: Annotated[auth.Principal, Depends(current_user)]) -> None:
    """Disconnect. Google is asked to forget the grant, and the row goes either way."""
    removed = await google_oauth.disconnect(user.id)
    log.info("google account disconnected", extra={"user_id": user.id, "removed": removed})


class JiraStatus(BaseModel):
    """Whether a Jira account is attached, which one, and the projects it opens here."""

    configured: bool
    display_name: str | None = None
    connected_at: str | None = None
    projects: list[str] = []


@router.get("/jira", response_model=JiraStatus)
async def jira_status(user: Annotated[auth.Principal, Depends(current_user)]) -> JiraStatus:
    """Which Jira account this person has connected, if any, and what it lets them read."""
    if not jira_oauth.configured():
        return JiraStatus(configured=False)
    row = await jira_oauth.connected(user.id)
    if row is None:
        return JiraStatus(configured=True)
    return JiraStatus(
        configured=True,
        display_name=row.display_name,
        connected_at=row.connected_at.isoformat(),
        projects=sorted(await readable_projects(user)),
    )


@router.get("/jira/start")
async def jira_start(user: Annotated[auth.Principal, Depends(current_user)]) -> RedirectResponse:
    """Send the browser to Atlassian's consent screen."""
    if not jira_oauth.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "this deployment has no Jira OAuth client"
        )
    return RedirectResponse(await jira_oauth.consent_url(user.id))


@router.get("/jira/callback")
async def jira_callback(
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Where Atlassian sends the browser back. Connects the account, then returns to the app."""
    # Refresh access now rather than at the next sync.
    return await _finish_connect(
        "jira", jira_oauth.connect, code, state, error, then=access.refresh
    )


@router.delete("/jira", status_code=status.HTTP_204_NO_CONTENT)
async def jira_disconnect(user: Annotated[auth.Principal, Depends(current_user)]) -> None:
    """Disconnect."""
    removed = await jira_oauth.disconnect(user.id)
    log.info("jira account disconnected", extra={"user_id": user.id, "removed": removed})


async def _finish_connect(
    provider: str,
    connect: Callable[[str, str], Awaitable[_Connected]],
    code: str | None,
    state: str | None,
    error: str | None,
    then: Callable[[int], Awaitable[object]] | None = None,
) -> RedirectResponse:
    """The end of a consent round, the same for every provider: always a redirect."""
    if error or not code or not state:
        return _back(f"{provider}_error={error or 'cancelled'}")
    try:
        row = await connect(state, code)
    except Exception:  # any failure must still redirect to a readable page
        log.warning(f"{provider} connect failed", exc_info=True)
        return _back(f"{provider}_error=failed")
    if then is not None:
        await then(row.user_id)
    log.info(f"{provider} account connected", extra={"user_id": row.user_id})
    return _back(f"{provider}=connected")


def _back(outcome: str) -> RedirectResponse:
    """Back to the app, carrying what happened."""
    base = get_settings().public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/app/home?{outcome}")
