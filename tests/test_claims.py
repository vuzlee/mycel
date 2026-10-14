"""A job is run by one worker at a time."""

from typing import Any

import pytest

from mycel.domains import chat
from mycel.infra.redis import claims
from mycel.queue.job import Job, JobKind
from tests.fakes import FakeRedis

pytestmark = pytest.mark.anyio


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()

    async def client() -> FakeRedis:
        return fake

    monkeypatch.setattr(claims, "get_client", client)
    return fake


async def test_a_claim_is_held_until_released(redis: FakeRedis) -> None:
    assert await claims.take("job-1", 60) is True
    assert await claims.take("job-1", 60) is False

    await claims.release("job-1")

    assert await claims.take("job-1", 60) is True


async def test_a_copy_of_a_running_job_is_retried_not_run(
    monkeypatch: pytest.MonkeyPatch, redis: FakeRedis
) -> None:
    """Two workers on one job would pay twice and interleave one stream."""

    async def prepared(job: Job) -> Any:
        return object()

    monkeypatch.setattr(chat, "_prepare", prepared)
    await claims.take("job-1", 60)

    with pytest.raises(chat.AlreadyRunning):
        await chat.run(Job(kind=JobKind.CHAT, payload={"question": "q"}, job_id="job-1"))
