"""What controllers declare via `Depends()`: auth, DB session, pagination.

**Auth lives here rather than in middleware**, because `Depends()` wins on three counts:

  - Middleware runs for *every* route, so it has to carry its own exclusion list for
    `/health`, `/docs`, `/openapi.json`. A dependency applies only where declared.
  - Dependencies reach the OpenAPI schema — `/docs` shows a padlock, and generated
    clients know a token is required.
  - A controller receives `user: User = Depends(current_user)` directly: typed, and
    checkable under mypy strict. Middleware only stuffs things into `request.state`,
    where mypy sees nothing.

A dependency answers only *who you are*; *which reports you may see* belongs to
`services/permission.py`, which needs business context the HTTP layer does not have.
"""

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from mycel.agents.core.config import AgentSettings
from mycel.core.config import Settings, get_settings


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
