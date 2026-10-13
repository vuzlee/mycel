"""Per-IP and per-user request limits, as route dependencies."""

from fastapi import Depends, HTTPException, Request, params, status
from redis.exceptions import RedisError

from mycel.api.dependencies import CurrentUser
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.redis import rate

log = get_logger(__name__)


async def _check(scope: str, key: str, per_minute: int) -> None:
    if not get_settings().rate_limits_enabled:
        return
    try:
        verdict = await rate.hit(scope, key, per_minute)
    except RedisError:
        # A limiter must not take login down with it.
        log.warning("rate limit unchecked, redis unreachable", extra={"scope": scope})
        return
    if not verdict.allowed:
        log.warning("rate limited", extra={"scope": scope})
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many requests; wait and try again",
            headers={"Retry-After": str(verdict.retry_after)},
        )


def per_ip(scope: str, per_minute: int) -> params.Depends:
    """At most `per_minute` calls a minute from one client address."""

    async def check(request: Request) -> None:
        await _check(scope, request.client.host if request.client else "unknown", per_minute)

    dependency: params.Depends = Depends(check)
    return dependency


def per_user(scope: str, per_minute: int) -> params.Depends:
    """At most `per_minute` calls a minute from one signed-in person."""

    async def check(user: CurrentUser) -> None:
        await _check(scope, str(user.id), per_minute)

    dependency: params.Depends = Depends(check)
    return dependency
