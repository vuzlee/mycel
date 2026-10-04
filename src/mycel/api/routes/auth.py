"""Sign up, sign in, sign out, and ask who you are.

    POST /auth/register   create an account, without signing in with it
    POST /auth/login      exchange email and password for a session cookie
    POST /auth/logout     delete the session, whichever one the cookie names
    POST /auth/password   change the password, ending every other session
    POST /auth/forgot     ask for a reset link, whether or not the address is known
    POST /auth/reset      spend a reset link and set a new password
    GET  /auth/me         who the cookie belongs to, or 401
    GET  /auth/google         which Google account is connected, if any
    GET  /auth/google/start   send the browser to Google's consent screen
    GET  /auth/google/callback  where Google sends it back; connects the account
    DELETE /auth/google       disconnect, and tell Google to forget the grant

**The two Google routes are `GET` and redirect, unlike everything else here.** They are
browser navigations rather than calls from the page: consent happens on Google's own screen,
so the trip out and the trip back are both address-bar traffic, and `SameSite=Lax` sends the
session cookie on a top-level GET. What ties the return trip to the person who left is a
`state` value they never see — see `services/google_oauth.py`.

**The token goes in a cookie, not in the body.** A token a page can read is a token a
cross-site script can steal, so it is set `HttpOnly` and the browser is the only thing
that ever handles it. `SameSite=Lax` keeps it off cross-site POSTs, which is the CSRF
defence this needs while every mutating call comes from the app's own pages.

`secure` follows the environment: a cookie marked secure is never sent over plain HTTP,
which would make local development fail in a way that looks like a login bug.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.api.dependencies import SESSION_COOKIE, current_user, get_db
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.notify import mail
from mycel.services import auth, google_oauth, jira_oauth

router = APIRouter(prefix="/auth", tags=["auth"])

log = get_logger(__name__)


class Credentials(BaseModel):
    """An email and a password. The same shape signs up and signs in."""

    #: Not `EmailStr`: that pulls in `email-validator` to enforce a spec nobody logs in
    #: by. The address is an identifier here, and `services/auth.py` lowercases it.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=auth.MIN_PASSWORD, max_length=1024)


class Registration(Credentials):
    """Credentials plus the invite code, when the deployment asks for one."""

    #: Ignored where registration is open, so the same form posts to both.
    invite_code: str | None = Field(default=None, max_length=256)


class PasswordChange(BaseModel):
    """The old password and the new one. Both, always — see the route."""

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=auth.MIN_PASSWORD, max_length=1024)


class ForgotRequest(BaseModel):
    """An address to send a reset link to, if it has an account."""

    email: str = Field(min_length=3, max_length=254)


class PasswordReset(BaseModel):
    """The token out of the link, and the password to set with it."""

    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=auth.MIN_PASSWORD, max_length=1024)


class UserResponse(BaseModel):
    """A person, as the API describes them. No hash, by construction — see `Principal`."""

    id: int
    email: str


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def register(
    body: Registration,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Create an account. No session: the new account has to be signed into.

    Deliberately not signing in here. Registering and signing in are separate decisions,
    and a form that silently does both leaves someone unsure which password went in —
    the first thing they do with a new account should be prove it works.
    """
    user = await auth.register(session, body.email, body.password, body.invite_code)
    log.info("user registered", extra={"user_id": user.id})
    return UserResponse(id=user.id, email=user.email)


@router.post("/login", response_model=UserResponse)
async def login(
    body: Credentials,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Exchange an email and password for a session cookie."""
    user = await auth.authenticate(session, body.email, body.password)
    await _issue_cookie(session, response, user.id)
    return UserResponse(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """End the session. Deliberately not behind `current_user`.

    Logging out with a cookie that has already expired must still clear the cookie — a
    401 here would leave a browser holding a token it can never get rid of.
    """
    if mycel_session:
        await auth.close_session(session, mycel_session)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    user: Annotated[auth.Principal, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """Change the password. The current one is required even though the cookie is valid.

    Every other session of this user ends; this one survives, so the person doing it is not
    logged out of the tab they are typing in. There is no forgotten-password flow: a reset
    link needs somewhere to send mail, and nothing in `notify/` sends any.
    """
    ended = await auth.change_password(
        session, user.id, body.current_password, body.new_password, keep_token=mycel_session
    )
    log.info("password changed", extra={"user_id": user.id, "sessions_ended": ended})


@router.post("/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Ask for a reset link. 202 whether or not the address has an account.

    Answering differently would make this endpoint a list of who is registered, which is
    the leak `authenticate` already refuses to be. A deployment with no SMTP configured
    refuses outright instead: a link that is never sent is worse than a feature that says
    it is off.
    """
    if not mail.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this deployment cannot send mail")
    await auth.begin_password_reset(session, body.email)


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: PasswordReset,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spend a reset link. Every session of that account ends, including any still open."""
    ended = await auth.reset_password(session, body.token, body.new_password)
    log.info("password reset", extra={"sessions_ended": ended})


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[auth.Principal, Depends(current_user)]) -> UserResponse:
    """Who the cookie belongs to. The call the UI makes on load to decide what to show."""
    return UserResponse(id=user.id, email=user.email)


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
    if error or not code or not state:
        return _back(f"google_error={error or 'cancelled'}")
    try:
        row = await google_oauth.connect(state, code)
    except Exception as exc:
        # Broader than `GoogleError` on purpose. The promise above is that this url always
        # redirects, and Redis being down or the database refusing a write would otherwise
        # answer a browser with a raw 500 in the middle of a consent flow. Nothing was
        # connected either way, which is the only thing the person needs told.
        log.warning("google connect failed", extra={"detail": str(exc)})
        return _back("google_error=failed")
    log.info("google account connected", extra={"user_id": row.user_id})
    return _back("google=connected")


@router.delete("/google", status_code=status.HTTP_204_NO_CONTENT)
async def google_disconnect(user: Annotated[auth.Principal, Depends(current_user)]) -> None:
    """Disconnect. Google is asked to forget the grant, and the row goes either way."""
    removed = await google_oauth.disconnect(user.id)
    log.info("google account disconnected", extra={"user_id": user.id, "removed": removed})


class JiraStatus(BaseModel):
    """Whether a Jira account is attached, which one, and whether it drives the sync.

    `configured` is about the deployment rather than the person, as the Google one is.
    `is_syncer` is about the deployment too, in a different way: it says this person's
    grant is what every background sync runs on, so disconnecting stops the syncing.
    """

    configured: bool
    display_name: str | None = None
    connected_at: str | None = None
    is_syncer: bool = False
    #: Whether anybody at all drives the sync. False with `configured` true means the
    #: dashboard is going stale and the next person to connect fixes it.
    syncer_exists: bool = False
    #: When a background sync last succeeded on this grant, for the person who holds it.
    last_sync_at: str | None = None


@router.get("/jira", response_model=JiraStatus)
async def jira_status(user: Annotated[auth.Principal, Depends(current_user)]) -> JiraStatus:
    """Which Jira account this person has connected, if any, and who drives the sync."""
    if not jira_oauth.configured():
        return JiraStatus(configured=False)
    row = await jira_oauth.connected(user.id)
    exists = await jira_oauth.syncer() is not None
    if row is None:
        return JiraStatus(configured=True, syncer_exists=exists)
    return JiraStatus(
        configured=True,
        display_name=row.display_name,
        connected_at=row.connected_at.isoformat(),
        is_syncer=row.is_syncer,
        syncer_exists=exists,
        last_sync_at=row.last_sync_at.isoformat() if row.last_sync_at else None,
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
    if error or not code or not state:
        return _back(f"jira_error={error or 'cancelled'}")
    try:
        row = await jira_oauth.connect(state, code)
    except Exception as exc:
        log.warning("jira connect failed", extra={"detail": str(exc)})
        return _back("jira_error=failed")
    log.info("jira account connected", extra={"user_id": row.user_id})
    return _back("jira=connected")


@router.delete("/jira", status_code=status.HTTP_204_NO_CONTENT)
async def jira_disconnect(user: Annotated[auth.Principal, Depends(current_user)]) -> None:
    """Disconnect. Atlassian is not told — it publishes no revoke endpoint for a 3LO
    refresh token, so the person finishes the job at id.atlassian.com and the screen
    says so. Disconnecting the syncer stops the background sync."""
    removed = await jira_oauth.disconnect(user.id)
    log.info("jira account disconnected", extra={"user_id": user.id, "removed": removed})


def _back(outcome: str) -> RedirectResponse:
    """Back to the app, carrying what happened. Relative to `public_base_url`, which is the
    one place this deployment's own address is written down."""
    base = get_settings().public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/app/home?{outcome}")


async def _issue_cookie(session: AsyncSession, response: Response, user_id: int) -> None:
    """Open a session and attach it to the response."""
    token, expires_at = await auth.open_session(session, user_id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().mycel_env != "dev",
        path="/",
    )
