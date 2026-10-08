"""What routes declare via `Depends()`: auth, DB session, pagination.

**Auth lives here rather than in middleware**, because `Depends()` wins on three counts:

  - Middleware runs for *every* route, so it has to carry its own exclusion list for
    `/health`, `/docs`, `/openapi.json`. A dependency applies only where declared.
  - Dependencies reach the OpenAPI schema — `/docs` shows a padlock, and generated
    clients know a token is required.
  - A route receives `user: User = Depends(current_user)` directly: typed, and
    checkable under mypy strict. Middleware only stuffs things into `request.state`,
    where mypy sees nothing.

A dependency answers only *who you are*; *which projects you may see* belongs to
`services/permission.py`, which needs business context the HTTP layer does not have.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.session import session_scope
from mycel.services.auth import Principal, session_user

#: The cookie a browser sends back. `HttpOnly` and `SameSite=Lax` are set where it is
#: written, in `api/routes/auth.py`; this side only needs its name.
SESSION_COOKIE = "mycel_session"


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session per request, committed if the handler returns and rolled back if not.

    Use it as `Depends(get_db, scope="function")` (`Db`). Since FastAPI 0.118 the default
    scope commits *after* the response is sent, so a client that logs in and calls the
    next route at once can arrive before its session row exists.
    """
    async with session_scope() as session:
        yield session


#: A request's database session, committed before the response leaves.
Db = Annotated[AsyncSession, Depends(get_db, scope="function")]


async def current_user(
    session: Db,
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Principal:
    """Who is calling, or 401.

    No cookie, an unknown token and an expired one are the same answer: there is nobody
    here. Distinguishing them in the response would tell an attacker which tokens once
    existed.
    """
    user = mycel_session and await session_user(session, mycel_session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not signed in",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user
