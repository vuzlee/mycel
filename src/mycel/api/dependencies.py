"""What routes declare via `Depends()`: auth and the DB session."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.session import session_scope
from mycel.services.auth import Principal, session_user

#: The cookie a browser sends back.
SESSION_COOKIE = "mycel_session"


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session per request, committed if the handler returns and rolled back if not."""
    async with session_scope() as session:
        yield session


#: A request's database session, committed before the response leaves.
Db = Annotated[AsyncSession, Depends(get_db, scope="function")]


async def current_user(
    session: Db,
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Principal:
    """Who is calling, or 401."""
    user = mycel_session and await session_user(session, mycel_session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not signed in",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user
