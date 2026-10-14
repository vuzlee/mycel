"""What routes declare via `Depends()`: auth and the DB session."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.principal import Principal
from mycel.infra.postgres.session import session_scope
from mycel.services.auth import session_user

#: The cookie a browser sends back.
SESSION_COOKIE = "mycel_session"


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session per request, committed if the handler returns and rolled back if not."""
    async with session_scope() as session:
        yield session


#: A request's database session, committed before the response leaves.
Db = Annotated[AsyncSession, Depends(get_db, scope="function")]


async def signed_in(
    mycel_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Principal | None:
    """Who is calling, or None. Its own short transaction: the handler's work needs the pool."""
    if not mycel_session:
        return None
    async with session_scope() as session:
        return await session_user(session, mycel_session)


async def current_user(
    user: Annotated[Principal | None, Depends(signed_in)],
) -> Principal:
    """Who is calling, or 401."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not signed in",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user


CurrentUser = Annotated[Principal, Depends(current_user)]
MaybeUser = Annotated[Principal | None, Depends(signed_in)]
