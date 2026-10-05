"""Daily question quotas for knowledge questions: one per user, one for all of RAG.

Reserved before Gemini is called and given back if the call fails, so a failed question
costs nothing. Lives on the noeviction server: an evicted counter would refund a day.
"""

from datetime import UTC, datetime

from mycel.infra.redis.client import get_client

TTL_SECONDS = 2 * 24 * 3600


def _day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _keys(user_id: int) -> tuple[str, str]:
    day = _day()
    return f"quota:ask:{user_id}:{day}", f"quota:ask:all:{day}"


async def remaining(user_id: int, per_user: int, system: int) -> int:
    """Questions this user can still ask today, bounded by what RAG has left overall."""
    redis = await get_client()
    mine, everyone = _keys(user_id)
    used_mine, used_all = await redis.mget(mine, everyone)
    return max(0, min(per_user - int(used_mine or 0), system - int(used_all or 0)))


async def reserve(user_id: int, per_user: int, system: int) -> bool:
    """Take one question from both counters, or neither."""
    redis = await get_client()
    mine, everyone = _keys(user_id)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(mine)
        pipe.expire(mine, TTL_SECONDS)
        pipe.incr(everyone)
        pipe.expire(everyone, TTL_SECONDS)
        used_mine, _, used_all, _ = await pipe.execute()
    if int(used_mine) <= per_user and int(used_all) <= system:
        return True
    await release(user_id)
    return False


async def release(user_id: int) -> None:
    """Give a reserved question back."""
    redis = await get_client()
    mine, everyone = _keys(user_id)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.decr(mine)
        pipe.decr(everyone)
        await pipe.execute()
