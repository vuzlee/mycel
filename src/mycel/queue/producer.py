"""Publish a job, persistent and confirmed, to the queue its kind routes to."""

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel, AbstractExchange
from aiormq.exceptions import ChannelNotFoundEntity

from mycel.core.logging import get_logger
from mycel.queue import context, topology
from mycel.queue.connection import channel, get_connection
from mycel.queue.job import INGEST_KINDS, Job
from mycel.queue.retry import ATTEMPT_HEADER

log = get_logger(__name__)

#: The connection the topology was last declared on; a new one declares again.
_declared_on: object | None = None


def queue_for(job: Job) -> str:
    """Which queue, and so which pool of workers, takes this kind of work."""
    return topology.INGEST_QUEUE if job.kind in INGEST_KINDS else topology.QUEUE


async def publish(job: Job) -> str:
    """Put one job on the queue and return its `job_id`."""
    async with channel() as ch:
        exchange = await _exchange(ch)

        headers = context.inject()
        headers[ATTEMPT_HEADER] = 0

        message = Message(
            body=job.model_dump_json().encode(),
            content_type="application/json",
            # Persistent, or a broker restart drops it from the durable queue.
            delivery_mode=DeliveryMode.PERSISTENT,
            headers=headers,
            message_id=job.job_id,
        )

        # aio-pika waits for the broker's confirm, so returning means the broker has it.
        try:
            await exchange.publish(message, routing_key=queue_for(job))
        except ChannelNotFoundEntity:
            # The broker lost its topology (a wiped volume); the next publish declares it.
            _forget()
            raise

    log.info(
        "job published",
        extra={"job_id": job.job_id, "kind": str(job.kind)},
    )
    return job.job_id


async def _exchange(ch: AbstractChannel) -> AbstractExchange:
    """Declare the topology once per connection; after that, only look the exchange up."""
    global _declared_on
    connection = await get_connection()
    if _declared_on is not connection:
        topo = await topology.declare(ch)
        _declared_on = connection
        return topo.exchange
    return await ch.get_exchange(topology.EXCHANGE, ensure=False)


def _forget() -> None:
    global _declared_on
    _declared_on = None
