"""Sign in with Google or an emailed code, sign out, and ask who you are."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.api.dependencies import SESSION_COOKIE, CurrentUser, Db
from mycel.api.limits import per_ip
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.services import auth, google_signin, signin_code
from mycel.services.oauth import STATE_TTL_SECONDS

router = APIRouter(prefix="/auth", tags=["auth"])

log = get_logger(__name__)

#: Per client address. A code request sends mail; a verify guesses a code.
CODE_PER_MINUTE = 5
VERIFY_PER_MINUTE = 10

#: Binds a Google round to the browser that started it.
OIDC_COOKIE = "mycel_oidc"


class CodeRequest(BaseModel):
    #: Not `EmailStr`: that pulls in `email-validator` to enforce a spec nobody signs in by.
    email: str = Field(min_length=3, max_length=254)


class CodeCheck(CodeRequest):
    code: str = Field(min_length=4, max_length=12)


class UserResponse(BaseModel):
    """A person, as the API describes them."""

    id: int
    email: str


class Methods(BaseModel):
    """Which ways in this deployment offers, so the page shows only those."""

    google: bool
    code: bool


@router.get("/methods", response_model=Methods)
async def methods() -> Methods:
    return Methods(google=google_signin.configured(), code=signin_code.configured())


@router.get("/google/signin")
async def start_google_signin(
    hint: Annotated[str | None, Query(max_length=254)] = None,
    next: Annotated[str | None, Query(max_length=512)] = None,  # noqa: A002 - the URL's own word
) -> RedirectResponse:
    """Send the browser to Google, straight to `hint`'s password when one is given."""
    if not google_signin.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "this deployment has no Google client"
        )
    url, state = await google_signin.start(hint, next)
    response = RedirectResponse(url)
    response.set_cookie(
        OIDC_COOKIE,
        state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        # Lax: the cookie rides the top-level GET back from Google.
        samesite="lax",
        secure=_secure(),
        # Both the start and the shared callback live under it.
        path="/auth/google",
    )
    return response


async def finish_google_signin(
    session: Db,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    mycel_oidc: Annotated[str | None, Cookie(alias=OIDC_COOKIE)] = None,
) -> RedirectResponse:
    """A sign-in coming back through the shared callback. Always a redirect, never an error page."""
    if error or not code or not state:
        return _to_login(error or "cancelled")
    try:
        who = await google_signin.finish(state, mycel_oidc, code)
        user = await auth.account_for(session, who.email, who.sub)
    except (google_signin.SignInError, auth.AuthError) as exc:
        log.warning("google sign-in refused", extra={"error": str(exc)})
        return _to_login("refused")
    except Exception:  # any failure must still land on a readable page
        log.warning("google sign-in failed", exc_info=True)
        return _to_login("failed")

    response = RedirectResponse(f"{_base()}{who.next}")
    await _issue_cookie(session, response, user.id)
    response.delete_cookie(OIDC_COOKIE, path="/auth/google")
    log.info("signed in with google", extra={"user_id": user.id})
    return response


@router.post(
    "/code",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[per_ip("signin-code", CODE_PER_MINUTE)],
)
async def request_code(body: CodeRequest, background: BackgroundTasks) -> None:
    """Mail a sign-in code. 202 whatever the address, so this cannot map who has an account."""
    if not signin_code.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this deployment cannot send mail")
    code = await signin_code.issue(body.email)
    if code is not None:
        # After the response, so its timing says nothing either.
        background.add_task(signin_code.send, body.email, code)


@router.post(
    "/code/verify",
    response_model=UserResponse,
    dependencies=[per_ip("signin-verify", VERIFY_PER_MINUTE)],
)
async def verify_code(body: CodeCheck, response: Response, session: Db) -> UserResponse:
    """Exchange a right code for a session; the first one makes the account."""
    email = await signin_code.spend(body.email, body.code)
    user = await auth.account_for(session, email)
    await _issue_cookie(session, response, user.id)
    log.info("signed in with a code", extra={"user_id": user.id})
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


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: CurrentUser,
    response: Response,
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> UserResponse:
    """Who the cookie belongs to; called on every page load, so it also extends the cookie."""
    if mycel_session:
        _set_session_cookie(response, mycel_session)
    return UserResponse(id=user.id, email=user.email)


async def _issue_cookie(session: AsyncSession, response: Response, user_id: int) -> None:
    """Open a session and attach it to the response."""
    _set_session_cookie(response, await auth.open_session(session, user_id))


def _set_session_cookie(response: Response, token: str) -> None:
    """The session cookie, alive as long as the session row: 14 days from now."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=_secure(),
        path="/",
    )


def _to_login(reason: str) -> RedirectResponse:
    return RedirectResponse(f"{_base()}/app/login?error={reason}")


def _base() -> str:
    return get_settings().public_base_url.rstrip("/")


def _secure() -> bool:
    return get_settings().mycel_env != "dev"
