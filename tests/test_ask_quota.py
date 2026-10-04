"""The two daily quotas against a real Redis: per user, and for all of RAG."""

import os
from collections.abc import AsyncIterator

import pytest

from mycel.infra.redis import quota
from mycel.infra.redis.client import get_client

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("REDIS_URL"), reason="no redis"),
]


@pytest.fixture(autouse=True)
async def clean() -> AsyncIterator[None]:
    redis = await get_client()

    async def wipe() -> None:
        keys = [k async for k in redis.scan_iter("quota:ask:*")]
        if keys:
            await redis.delete(*keys)

    await wipe()
    yield
    await wipe()


class TestQuota:
    async def test_a_user_stops_at_their_own_limit(self) -> None:
        assert await quota.reserve(1, per_user=2, system=10)
        assert await quota.reserve(1, per_user=2, system=10)
        assert not await quota.reserve(1, per_user=2, system=10)
        assert await quota.remaining(1, per_user=2, system=10) == 0

    async def test_the_system_limit_stops_everyone(self) -> None:
        assert await quota.reserve(1, per_user=10, system=2)
        assert await quota.reserve(2, per_user=10, system=2)
        assert not await quota.reserve(3, per_user=10, system=2)
        assert await quota.remaining(3, per_user=10, system=2) == 0

    async def test_a_refused_reservation_takes_nothing(self) -> None:
        await quota.reserve(1, per_user=1, system=10)
        await quota.reserve(1, per_user=1, system=10)

        assert await quota.remaining(2, per_user=10, system=10) == 9

    async def test_release_gives_it_back(self) -> None:
        await quota.reserve(1, per_user=1, system=10)
        await quota.release(1)

        assert await quota.remaining(1, per_user=1, system=10) == 1
