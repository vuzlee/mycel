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
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.agents.core.config import AgentSettings
from mycel.core.config import Settings, get_settings
from mycel.infra.postgres.session import session_scope
from mycel.services.auth import Principal, session_user

#: The cookie a browser sends back. `HttpOnly` and `SameSite=Lax` are set where it is
#: written, in `api/routes/auth.py`; this side only needs its name.
SESSION_COOKIE = "mycel_session"


@dataclass(frozen=True, slots=True)
class ApiConfig:
    """What the HTTP layer needs that is not an agent's own setting.

    Separate from `AgentSettings` because these are knobs of the *service*, not of any one
    agent: a ceiling applies to a request whichever agent ends up running.
    """

    #: Most a single request may spend. Not a per-agent setting: a request is what a
    #: caller pays for, and the orchestrator's delegated runs all bill against this one
    #: ceiling (see `runner.delegate`).
    ceiling_usd: Decimal = Decimal("0.50")


@lru_cache(maxsize=1)
def get_api_config() -> ApiConfig:
    """The service's own knobs, read once."""
    return ApiConfig()


@lru_cache(maxsize=1)
def get_agent_settings() -> AgentSettings:
    """The orchestrator's settings, resolved once per process rather than per request.

    `AgentSettings.from_config` reads YAML off disk. Doing that inside a handler turns
    every request into file I/O for a value that cannot change without a restart.
    """
    return AgentSettings.from_config("orchestrator")


def get_settings_dependency() -> Settings:
    """Environment settings, for handlers that need them. Cached by `get_settings`."""
    return get_settings()


def reset_caches() -> None:
    """Drop the cached config. For tests, and for `create_app` building a fresh app.

    Without this a test that sets an environment variable gets the previous test's
    settings, which fails in whichever order pytest happens to run them.
    """
    get_api_config.cache_clear()
    get_agent_settings.cache_clear()


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session per request, committed if the handler returns and rolled back if not."""
    async with session_scope() as session:
        yield session


async def current_user(
    session: Annotated[AsyncSession, Depends(get_db)],
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
