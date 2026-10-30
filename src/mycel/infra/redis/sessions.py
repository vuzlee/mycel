"""Who a session cookie names, briefly, on the evicting cache server.

Keyed by a hash of the token: the cookie is a credential and is never written here as is.
"""

import hashlib

from mycel.core.principal import Principal
from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_cache_client


def _key(token: str) -> str:
    return _kv.key("session", hashlib.sha256(token.encode()).hexdigest())


async def get(token: str) -> Principal | None:
    found = await _kv.get(await get_cache_client(), _key(token))
    return None if found is None else Principal(id=found["id"], email=found["email"])


async def put(token: str, user: Principal, ttl_seconds: int) -> None:
    value = {"id": user.id, "email": user.email}
    await _kv.put(await get_cache_client(), _key(token), value, ttl_seconds)


async def drop(token: str) -> None:
    await (await get_cache_client()).delete(_key(token))
