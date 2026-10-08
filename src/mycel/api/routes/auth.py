"""Sign up, sign in, sign out, and ask who you are."""

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.api.dependencies import SESSION_COOKIE, CurrentUser, Db
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra import smtp
from mycel.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])

log = get_logger(__name__)


class Credentials(BaseModel):
    """An email and a password. The same shape signs up and signs in."""

    #: Not `EmailStr`: that pulls in `email-validator` to enforce a spec nobody logs in by.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=auth.MIN_PASSWORD, max_length=1024)


class Registration(Credentials):
    """Credentials plus the invite code, when the deployment asks for one."""

    #: Ignored where registration is open, so the same form posts to both.
    invite_code: str | None = Field(default=None, max_length=256)


class PasswordChange(BaseModel):
    """The old password and the new one. Both are required."""

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
    session: Db,
) -> UserResponse:
    """Create an account. No session: the new account has to be signed into."""
    user = await auth.register(session, body.email, body.password, body.invite_code)
    log.info("user registered", extra={"user_id": user.id})
    return UserResponse(id=user.id, email=user.email)


@router.post("/login", response_model=UserResponse)
async def login(
    body: Credentials,
    response: Response,
    session: Db,
) -> UserResponse:
    """Exchange an email and password for a session cookie."""
    user = await auth.authenticate(session, body.email, body.password)
    await _issue_cookie(session, response, user.id)
    return UserResponse(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: Db,
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """End the session. Deliberately not behind `current_user`."""
    if mycel_session:
        await auth.close_session(session, mycel_session)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    user: CurrentUser,
    session: Db,
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """Change the password. The current one is required even though the cookie is valid."""
    ended = await auth.change_password(
        session, user.id, body.current_password, body.new_password, keep_token=mycel_session
    )
    log.info("password changed", extra={"user_id": user.id, "sessions_ended": ended})


@router.post("/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotRequest,
    session: Db,
) -> None:
    """Ask for a reset link. 202 whether or not the address has an account."""
    if not smtp.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this deployment cannot send mail")
    await auth.begin_password_reset(session, body.email)


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: PasswordReset,
    session: Db,
) -> None:
    """Spend a reset link. Every session of that account ends, including any still open."""
    ended = await auth.reset_password(session, body.token, body.new_password)
    log.info("password reset", extra={"sessions_ended": ended})


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentUser) -> UserResponse:
    """Who the cookie belongs to. The call the UI makes on load to decide what to show."""
    return UserResponse(id=user.id, email=user.email)


async def _issue_cookie(session: AsyncSession, response: Response, user_id: int) -> None:
    """Open a session and attach it to the response."""
    token = await auth.open_session(session, user_id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().mycel_env != "dev",
        path="/",
    )
