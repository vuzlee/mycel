"""A job is run by one worker at a time, and a dead worker does not hold it for long."""

import asyncio
import os
from typing import Any

import pytest

from mycel.domains import chat
from mycel.infra.redis import claims
from mycel.queue.job import Job, JobKind
from mycel.queue.topology import RETRY_DELAYS_MS

pytestmark = pytest.mark.anyio


class Redis:
    """SET NX EX, and the two scripts, against a dict; expiry is driven by hand."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int = 0) -> bool | None:
        if nx and key in self.values:
            return None
        self.values[key], self.ttls[key] = value, ex
        return True

    async def eval(self, script: str, n: int, key: str, token: str, *args: str) -> int:
        if self.values.get(key) != token:
            return 0
        if "DEL" in script:
            del self.values[key]
        else:
            self.ttls[key] = int(args[0])
        return 1

    def expire(self, key: str) -> None:
        self.values.pop(key, None)


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Redis:
    fake = Redis()

    async def client() -> Redis:
        return fake

    monkeypatch.setattr(claims, "get_client", client)
    return fake


async def test_a_claim_is_held_until_the_block_ends(redis: Redis) -> None:
    async with claims.holding("job-1"):
        with pytest.raises(claims.AlreadyRunning):
            async with claims.holding("job-1"):
                pass

    async with claims.holding("job-1"):
        pass


async def test_a_dead_worker_frees_the_job_before_the_retry_comes(redis: Redis) -> None:
    """A 15 minute claim outlived every retry (5 s, 30 s, 2 m) and failed the question."""
    assert claims.TTL_SECONDS * 1000 < RETRY_DELAYS_MS[1]
    assert claims.RENEW_SECONDS * 3 <= claims.TTL_SECONDS

    await redis.set("mycel:claim:job-1", "dead-worker", nx=True, ex=claims.TTL_SECONDS)
    redis.expire("mycel:claim:job-1")  # nobody renewed it

    async with claims.holding("job-1"):
        pass


async def test_a_running_job_keeps_renewing(redis: Redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claims, "RENEW_SECONDS", 0.01)
    renewed: list[int] = []
    real = redis.eval

    async def counting(script: str, n: int, key: str, token: str, *args: str) -> int:
        if "EXPIRE" in script:
            renewed.append(1)
        return await real(script, n, key, token, *args)

    monkeypatch.setattr(redis, "eval", counting)
    async with claims.holding("job-1"):
        await asyncio.sleep(0.05)

    assert len(renewed) >= 2


async def test_a_late_release_does_not_free_someone_elses_claim(redis: Redis) -> None:
    """The claim expired and another worker took it; the first one's release must not drop it."""
    async with claims.holding("job-1"):
        redis.values["mycel:claim:job-1"] = "the-new-holder"

    assert redis.values["mycel:claim:job-1"] == "the-new-holder"


async def test_a_copy_of_a_running_job_is_retried_not_run(
    monkeypatch: pytest.MonkeyPatch, redis: Redis
) -> None:
    """Two workers on one job would pay twice and interleave one stream."""

    async def prepared(job: Job) -> Any:
        return object()

    monkeypatch.setattr(chat, "_prepare", prepared)
    await redis.set("mycel:claim:job-1", "other", nx=True, ex=25)

    with pytest.raises(claims.AlreadyRunning):
        await chat.run(Job(kind=JobKind.CHAT, payload={"question": "q"}, job_id="job-1"))


@pytest.mark.skipif(not os.environ.get("REDIS_URL"), reason="no Redis")
async def test_the_scripts_run_on_a_real_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renew and release scripts are Lua; a typo only shows on a real server."""
    from mycel.infra.redis.client import close_clients, get_client

    monkeypatch.setattr(claims, "RENEW_SECONDS", 0.05)
    name = "mycel:claim:test-real"
    client = await get_client()
    await client.delete(name)
    try:
        async with claims.holding("test-real"):
            await asyncio.sleep(0.15)
            assert 0 < await client.ttl(name) <= claims.TTL_SECONDS
        assert await client.exists(name) == 0
    finally:
        await client.delete(name)
        await close_clients()
