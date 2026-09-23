"""Publish a job to an exchange. The entry point from business code is `services/enqueue.py`.

The routing key picks the queue, and therefore which pool of workers takes the job — keeping
long bulk syncs off the queue that interactive chat jobs wait on.

Publish with `delivery_mode=PERSISTENT` to a durable queue, and with publisher confirms on:
losing a chat job leaves the user waiting for something that never arrives, which costs far
more than a few tens of milliseconds on publish. Both are off by default; a message published
without them is dropped silently when the broker restarts.

Call `context.inject()` before publishing, otherwise the trace breaks right here.
"""

from aio_pika import DeliveryMode, Message

from mycel.core.logging import get_logger
from mycel.queue import context, topology
from mycel.queue.connection import channel
from mycel.queue.job import Job
from mycel.queue.retry import ATTEMPT_HEADER

log = get_logger(__name__)


async def publish(job: Job) -> str:
    """Put one job on the queue and return its `job_id`.

    Declares the topology first. That is not wasted work on a hot path — declarations are
    idempotent and cheap — and it means the first publish after a cold start creates the
    queue rather than dropping the message into an unrouted void.
    """
    async with channel() as ch:
        topo = await topology.declare(ch)

        headers = context.inject()
        headers[ATTEMPT_HEADER] = 0

        message = Message(
            body=job.model_dump_json().encode(),
            content_type="application/json",
            # Without this the message is held in memory only, and a broker restart drops
            # it from a queue that is otherwise durable.
            delivery_mode=DeliveryMode.PERSISTENT,
            headers=headers,
            message_id=job.job_id,
            # The broker does not deduplicate on this; it is here so a message sitting in
            # `jobs.dlq` can be matched to the work it represents without parsing the body.
            correlation_id=job.idempotency_key,
        )

        # aio-pika waits for the broker's confirm by default, so this returning means the
        # broker has the message — not merely that it was written to a socket.
        await topo.exchange.publish(message, routing_key=topology.QUEUE)

    log.info(
        "job published",
        extra={"job_id": job.job_id, "kind": str(job.kind), "key": job.idempotency_key},
    )
    return job.job_id
