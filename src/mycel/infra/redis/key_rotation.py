"""Which key of an own model to try first, and which are cooling down. Indices only, never keys."""

from mycel.infra.redis._kv import key
from mycel.infra.redis.client import get_cache_client


def _cursor(model_id: int) -> str:
    return key("rr", "own", model_id)


def _cooling(model_id: int, position: int) -> str:
    return key("cooldown", "own", model_id, position)


async def next_start(model_id: int, count: int) -> int:
    """Round robin: each run starts one key further on than the last."""
    client = await get_cache_client()
    return int(await client.incr(_cursor(model_id)) - 1) % count


async def cooling(model_id: int, count: int) -> set[int]:
    """Positions set aside after a quota or auth failure, until their cooldown ends."""
    client = await get_cache_client()
    found = await client.mget([_cooling(model_id, i) for i in range(count)])
    return {i for i, v in enumerate(found) if v is not None}


async def cool(model_id: int, position: int, seconds: int) -> None:
    client = await get_cache_client()
    await client.set(_cooling(model_id, position), "1", ex=max(1, seconds))
