"""The queue against a real broker — the half `test_queue.py` cannot prove."""

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx
import pytest
from aio_pika import Message
from aio_pika.abc import AbstractChannel

from mycel.queue import replay, retry, topology
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
        for queue in (topo.jobs, *topo.retries, topo.dead):
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
        assert [q.name for q in again.retries] == [
            "jobs.retry.5s",
            "jobs.retry.30s",
            "jobs.retry.2m",
        ]
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

    async def test_a_second_publish_skips_the_declare_and_still_arrives(
        self, live: AbstractChannel
    ) -> None:
        first, second = _job("one"), _job("two")
        await publish(first)
        await publish(second)

        topo = await topology.declare(live)
        ids = []
        for _ in range(2):
            message = await topo.jobs.get(timeout=5)
            assert message is not None
            ids.append(message.message_id)
            await message.ack()
        assert ids == [first.job_id, second.job_id]


@needs_broker
class TestRejecting:
    async def test_a_failure_lands_in_the_retry_queue(self, live: AbstractChannel) -> None:
        """Not requeued to the head of `jobs`."""
        topo = await topology.declare(live)
        await publish(_job())
        incoming = await topo.jobs.get(timeout=5)
        assert incoming is not None

        await retry.reject(incoming, topo.dlx, reason="provider said 503")

        held = await topo.retries[0].get(timeout=5)
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

    async def test_the_first_retry_comes_back_after_its_delay(self, live: AbstractChannel) -> None:
        """The broker, not our code, moves it back: TTL, then dead-letter to `jobs`."""
        topo = await topology.declare(live)
        job = _job()
        await publish(job)
        message = await topo.jobs.get(timeout=5)
        assert message is not None
        await retry.reject(message, topo.dlx, reason="503")

        back = None
        for _ in range(40):
            back = await topo.jobs.get(fail=False)
            if back is not None:
                break
            await asyncio.sleep(0.25)
        assert back is not None, "not back within 10 s of a 5 s delay"
        assert back.message_id == job.job_id
        assert back.headers[retry.ATTEMPT_HEADER] == 1
        await back.ack()

    async def test_the_last_attempt_goes_to_the_dead_letter_queue(
        self, live: AbstractChannel
    ) -> None:
        """Attempt counting is ours, in a header."""
        topo = await topology.declare(live)
        await publish(_job())

        message = await topo.jobs.get(timeout=5)
        assert message is not None
        await retry.reject(message, topo.dlx, reason="try 1")

        # Each retry waits in the next, longer delay queue; taken before its TTL runs out.
        for n, queue in enumerate(topo.retries, start=2):
            held = await queue.get(timeout=5)
            assert held is not None
            assert retry.exhausted(held) is (n == topology.MAX_ATTEMPTS)
            await retry.reject(held, topo.dlx, reason=f"try {n}")

        parked = await topo.dead.get(timeout=5)
        assert parked is not None
        assert parked.headers[retry.ATTEMPT_HEADER] == topology.MAX_ATTEMPTS
        await parked.ack()


@needs_broker
class TestReplay:
    async def test_a_parked_job_goes_back_with_its_attempts_reset(
        self, live: AbstractChannel
    ) -> None:
        topo = await topology.declare(live)
        job = _job()
        await topo.dlx.publish(
            Message(
                job.model_dump_json().encode(),
                message_id=job.job_id,
                headers={retry.ATTEMPT_HEADER: topology.MAX_ATTEMPTS, "mycel-error": "boom"},
            ),
            routing_key=topology.DEAD_QUEUE,
        )

        assert (await replay.depths())[topology.DEAD_QUEUE] == 1
        assert await replay.replay(topology.DEAD_QUEUE) == 1

        message = await topo.jobs.get(timeout=5)
        assert message is not None and message.message_id == job.job_id
        assert message.headers[retry.ATTEMPT_HEADER] == 0
        assert "mycel-error" not in message.headers
        await message.ack()


@needs_broker
class TestTheWorkQueues:
    async def test_they_carry_no_broker_dead_lettering(self, live: AbstractChannel) -> None:
        """`retry.reject` routes every failure; a broker route would bypass the delays."""
        url = urlsplit(os.environ["RABBITMQ_URL"])
        api = f"http://{url.hostname}:15672/api/queues/%2F"
        async with httpx.AsyncClient(auth=(url.username or "", url.password or "")) as http:
            for name in (topology.QUEUE, topology.INGEST_QUEUE):
                arguments = (await http.get(f"{api}/{name}")).raise_for_status().json()["arguments"]
                assert "x-dead-letter-routing-key" not in arguments, name
