"""Publish a job, persistent and confirmed, to the queue its kind routes to."""

from aio_pika import DeliveryMode, Message

from mycel.core.logging import get_logger
from mycel.queue import context, topology
from mycel.queue.connection import channel
from mycel.queue.job import INGEST_KINDS, Job
from mycel.queue.retry import ATTEMPT_HEADER

log = get_logger(__name__)


def queue_for(job: Job) -> str:
    """Which queue, and so which pool of workers, takes this kind of work."""
    return topology.INGEST_QUEUE if job.kind in INGEST_KINDS else topology.QUEUE


async def publish(job: Job) -> str:
    """Put one job on the queue and return its `job_id`; declares the topology first."""
    async with channel() as ch:
        topo = await topology.declare(ch)

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
        await topo.exchange.publish(message, routing_key=queue_for(job))

    log.info(
        "job published",
        extra={"job_id": job.job_id, "kind": str(job.kind)},
    )
    return job.job_id
