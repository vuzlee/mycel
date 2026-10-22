"""An access token per person and provider, refreshed once per lifetime instead of per call."""

from collections.abc import Awaitable, Callable

from redis.exceptions import RedisError

from mycel.core.logging import get_logger
from mycel.infra.redis import access_tokens as store
from mycel.services.sealing import TokenUnreadable, seal, unseal

log = get_logger(__name__)

#: Dropped this long before the provider says it expires, so a call never carries a dead one.
MARGIN_SECONDS = 60

#: What a refresh returns: the token, and its lifetime in seconds when the provider said.
Fresh = tuple[str, int | None]


async def cached(provider: str, user_id: int, refresh: Callable[[], Awaitable[Fresh]]) -> str:
    """The cached token, or a refreshed one kept for its lifetime. A dead cache only costs time."""
    try:
        sealed = await store.get(provider, user_id)
        if sealed is not None:
            return unseal(sealed)
    except (RedisError, TokenUnreadable):
        log.warning("access token cache unreadable", extra={"provider": provider}, exc_info=True)

    token, lifetime = await refresh()
    ttl = (lifetime or 0) - MARGIN_SECONDS
    if ttl > 0:
        try:
            await store.put(provider, user_id, seal(token), ttl)
        except RedisError:
            log.warning("access token not cached", extra={"provider": provider}, exc_info=True)
    return token


async def forget(provider: str, user_id: int) -> None:
    """Drop the cached token, so a disconnect takes effect at once."""
    try:
        await store.drop(provider, user_id)
    except RedisError:
        log.warning("access token not dropped", extra={"provider": provider}, exc_info=True)


def lifetime(payload: dict[str, object]) -> int | None:
    """`expires_in` from a token response, when it is a number."""
    value = payload.get("expires_in")
    try:
        return int(value) if value is not None else None  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
