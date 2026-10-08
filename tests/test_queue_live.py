"""The queue against a real broker — the half `test_queue.py` cannot prove."""

import os
from collections.abc import AsyncIterator

import pytest
from aio_pika.abc import AbstractChannel

from mycel.queue import retry, topology
from mycel.queue.connection import channel, close_connection
from mycel.queue.job import Job, JobKind
from mycel.queue.producer import publish

pytestmark = pytest.mark.anyio

needs_broker = pytest.mark.skipif(
    not os.environ.get("RABBITMQ_URL"), reason="no broker is reachable"
)


@pytest.fixture
async def live() -> AsyncIterator[AbstractChannel]:
    """A channel with the topology declared, and all three queues emptied first."""
    async with channel() as ch:
        topo = await topology.declare(ch)
        for queue in (topo.jobs, topo.retry, topo.dead):
            await queue.purge()
        yield ch
    await close_connection()


def _job(question: str = "how is the quarter going?") -> Job:
    return Job(kind=JobKind.CHAT, payload={"question": question, "conversation_id": 0})


@needs_broker
class TestTopology:
    async def test_declaring_twice_agrees_with_itself(self, live: AbstractChannel) -> None:
        """A second declaration with different arguments is `PRECONDITION_FAILED`."""
        again = await topology.declare(live)

        assert again.jobs.name == topology.QUEUE
        assert again.retry.name == topology.RETRY_QUEUE
        assert again.dead.name == topology.DEAD_QUEUE


@needs_broker
class TestPublishing:
    async def test_a_published_job_arrives_in_jobs(self, live: AbstractChannel) -> None:
        """The routing key reaches the queue we think it does."""
        job = _job()

        assert await publish(job) == job.job_id

        topo = await topology.declare(live)
        message = await topo.jobs.get(timeout=5)
        assert message is not None
        assert message.message_id == job.job_id
        assert message.headers[retry.ATTEMPT_HEADER] == 0
        await message.ack()

    async def test_the_body_survives_the_round_trip(self, live: AbstractChannel) -> None:
        await publish(_job("did anything ship?"))

        topo = await topology.declare(live)
        message = await topo.jobs.get(timeout=5)
        assert message is not None
        assert Job.model_validate_json(message.body).payload["question"] == "did anything ship?"
        await message.ack()


@needs_broker
class TestRejecting:
    async def test_a_failure_lands_in_the_retry_queue(self, live: AbstractChannel) -> None:
        """Not requeued to the head of `jobs`."""
        topo = await topology.declare(live)
        await publish(_job())
        incoming = await topo.jobs.get(timeout=5)
        assert incoming is not None

        await retry.reject(incoming, topo.dlx, reason="provider said 503")

        held = await topo.retry.get(timeout=5)
        assert held is not None
        assert held.headers[retry.ATTEMPT_HEADER] == 1
        assert held.headers["mycel-error"] == "provider said 503"
        await held.ack()

    async def test_giving_up_parks_the_job_instead(self, live: AbstractChannel) -> None:
        """A body that will not parse gets no second attempt."""
        topo = await topology.declare(live)
        await publish(_job())
        incoming = await topo.jobs.get(timeout=5)
        assert incoming is not None

        await retry.reject(incoming, topo.dlx, reason="unparseable", give_up=True)

        parked = await topo.dead.get(timeout=5)
        assert parked is not None
        assert parked.headers[retry.ATTEMPT_HEADER] == topology.MAX_ATTEMPTS
        await parked.ack()

    async def test_the_last_attempt_goes_to_the_dead_letter_queue(
        self, live: AbstractChannel
    ) -> None:
        """Attempt counting is ours, in a header."""
        topo = await topology.declare(live)
        await publish(_job())

        message = await topo.jobs.get(timeout=5)
        assert message is not None
        await retry.reject(message, topo.dlx, reason="first")

        held = await topo.retry.get(timeout=5)
        assert held is not None
        assert not retry.exhausted(held)
        await retry.reject(held, topo.dlx, reason="second")

        again = await topo.retry.get(timeout=5)
        assert again is not None
        assert retry.exhausted(again)
        await retry.reject(again, topo.dlx, reason="third")

        parked = await topo.dead.get(timeout=5)
        assert parked is not None
        assert parked.headers[retry.ATTEMPT_HEADER] == topology.MAX_ATTEMPTS
        await parked.ack()
