"""Sign up, sign in, sign out, and ask who you are.

    POST /auth/register   create an account, without signing in with it
    POST /auth/login      exchange email and password for a session cookie
    POST /auth/logout     delete the session, whichever one the cookie names
    POST /auth/password   change the password, ending every other session
    POST /auth/forgot     ask for a reset link, whether or not the address is known
    POST /auth/reset      spend a reset link and set a new password
    GET  /auth/me         who the cookie belongs to, or 401

**The token goes in a cookie, not in the body.** A token a page can read is a token a
cross-site script can steal, so it is set `HttpOnly` and the browser is the only thing
that ever handles it. `SameSite=Lax` keeps it off cross-site POSTs, which is the CSRF
defence this needs while every mutating call comes from the app's own pages.

`secure` follows the environment: a cookie marked secure is never sent over plain HTTP,
which would make local development fail in a way that looks like a login bug.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.api.dependencies import SESSION_COOKIE, current_user, get_db
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.notify import mail
from mycel.services import auth

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
