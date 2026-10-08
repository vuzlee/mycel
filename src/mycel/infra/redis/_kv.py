"""JSON values under `mycel:` keys, each with a TTL."""

import json
from typing import Any

from redis.asyncio import Redis


def key(*parts: object) -> str:
    return ":".join(["mycel", *map(str, parts)])


async def put(client: Redis, name: str, value: str | dict[str, Any], ttl_seconds: int) -> None:
    await client.set(name, value if isinstance(value, str) else json.dumps(value), ex=ttl_seconds)


async def get(client: Redis, name: str) -> Any:
    raw = await client.get(name)
    return None if raw is None else json.loads(raw)


async def take(client: Redis, name: str) -> Any:
    """Read and delete in one step."""
    raw = await client.getdel(name)
    return None if raw is None else json.loads(raw)
