"""Connected accounts: Google and Jira, each on the person's own consent.

    GET    /auth/google            which Google account is connected, if any
    GET    /auth/google/start      send the browser to Google's consent screen
    GET    /auth/google/callback   where Google sends it back; connects the account
    DELETE /auth/google            disconnect, and tell Google to forget the grant
    GET    /auth/jira              which Jira account is connected, and what it opens
    GET    /auth/jira/start        send the browser to Atlassian's consent screen
    GET    /auth/jira/callback     where Atlassian sends it back; connects the account
    DELETE /auth/jira              disconnect; their project access goes with it

**The start and callback routes are `GET` and redirect.** They are browser navigations
rather than calls from the page: consent happens on the provider's own screen, so the trip
out and back are both address-bar traffic, and `SameSite=Lax` sends the session cookie on a
top-level GET. What ties the return trip to the person who left is a `state` value they
never see — see `services/oauth.py`.
"""

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
    """Whether a Google account is attached, and which one.

    `configured` is about the deployment rather than the person: a machine with no OAuth
    client cannot connect anything, and the screen has to say that instead of offering a
    button that leads to an error.
    """

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
    """Send the browser to Google's consent screen.

    A redirect rather than the url in a JSON body: the page would only put it in
    `location.href` anyway, and one fewer round trip is one fewer place the `state` can be
    dropped.
    """
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
    """Where Google sends the browser back. Connects the account, then returns to the app.

    Deliberately **not** behind `current_user`: the request arrives as a redirect from
    Google, and `state` is what says whose consent round it is. Reading the cookie as well
    would add nothing — a browser that has both is the same browser either way — and would
    break the case where consent finished in a window whose session had since been replaced.

    Always a redirect, never an error body: this url is displayed in an address bar, so a
    refusal has to land somewhere a person can read it. The outcome rides back as a query
    parameter and the settings panel says what happened.
    """
    return await _finish_connect("google", google_oauth.connect, code, state, error)


@router.delete("/google", status_code=status.HTTP_204_NO_CONTENT)
async def google_disconnect(user: Annotated[auth.Principal, Depends(current_user)]) -> None:
    """Disconnect. Google is asked to forget the grant, and the row goes either way."""
    removed = await google_oauth.disconnect(user.id)
    log.info("google account disconnected", extra={"user_id": user.id, "removed": removed})


class JiraStatus(BaseModel):
    """Whether a Jira account is attached, which one, and the projects it opens here.

    `configured` is about the deployment rather than the person, as the Google one is.
    `projects` is what Jira said this person may browse, the last time it was asked.
    """

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
    """Where Atlassian sends the browser back. Connects the account, then returns to the app.

    Not behind `current_user`, always a redirect, and broad in what it catches — all three
    for the reasons `google_callback` above gives. This url is displayed in an address bar,
    so a refusal has to land somewhere a person can read it.
    """
    # Access at once rather than at the next sync: connecting is what the person did to see
    # their projects, and fifteen minutes of an empty app would read as a broken connect.
    return await _finish_connect(
        "jira", jira_oauth.connect, code, state, error, then=access.refresh
    )


@router.delete("/jira", status_code=status.HTTP_204_NO_CONTENT)
async def jira_disconnect(user: Annotated[auth.Principal, Depends(current_user)]) -> None:
    """Disconnect. Atlassian is not told — it publishes no revoke endpoint for a 3LO
    refresh token, so the person finishes the job at id.atlassian.com and the screen
    says so. Their project access goes with the token."""
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
    """The end of a consent round, the same for every provider: always a redirect.

    Catches broadly on purpose. This url is displayed in an address bar, and Redis being
    down or the database refusing a write would otherwise answer a browser with a raw 500
    in the middle of a consent flow. Nothing was connected either way, which is the only
    thing the person needs told.
    """
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
    """Back to the app, carrying what happened. Relative to `public_base_url`, which is the
    one place this deployment's own address is written down."""
    base = get_settings().public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/app/home?{outcome}")
