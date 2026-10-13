"""Short-lived OAuth access tokens, sealed, on the evicting cache server."""

from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_cache_client


def _key(provider: str, user_id: int) -> str:
    return _kv.key("access", provider, user_id)


async def get(provider: str, user_id: int) -> str | None:
    found = await (await get_cache_client()).get(_key(provider, user_id))
    return None if found is None else str(found)


async def put(provider: str, user_id: int, sealed: str, ttl_seconds: int) -> None:
    await (await get_cache_client()).set(_key(provider, user_id), sealed, ex=ttl_seconds)


async def drop(provider: str, user_id: int) -> None:
    await (await get_cache_client()).delete(_key(provider, user_id))
