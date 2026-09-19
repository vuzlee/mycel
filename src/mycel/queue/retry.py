"""Tiered retry and dead-letter, built from a dead-letter exchange and a message TTL.

Do not `nack(requeue=True)`: the message goes back to the head of the queue and fails again
at once, burning a worker in a tight loop. Reject it without requeue instead, and let the
queue's `x-dead-letter-exchange` move it on:

    jobs            first attempt; rejected -> dead-letters to mycel.jobs.dlx
    jobs.retry      x-message-ttl 60s, dead-letters back to `jobs` when it expires
    jobs.dlq        out of attempts — kept for inspection, not silently dropped

The delay is the queue's TTL, not a consumer sleeping: nothing consumes `jobs.retry` at
all. A message sits there until it expires and the broker routes it onward by itself.

The attempt count is tracked in a header we write. The broker's own `x-death` header also
counts rejections per queue, but it is easier to read a counter we wrote than to sum that
array — and easier still to get wrong, since `x-death` counts per queue-and-reason rather
than per job.

Trace context travels in the headers across all three queues, so a job that lands in
`jobs.dlq` can still have its trace reopened from the moment the user pressed the button.
"""

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage

from mycel.core.logging import get_logger
from mycel.queue import topology

log = get_logger(__name__)

#: Where the attempt count lives. `x-`-prefixed names are the broker's own namespace, so
#: this one deliberately is not.
ATTEMPT_HEADER = "mycel-attempt"


def attempt_of(message: AbstractIncomingMessage) -> int:
    """How many times this job has already been tried.

    Absent or malformed means zero: a message published by an older deployment, or by hand
    through the management UI, is a first attempt rather than an error.
    """
    raw = (message.headers or {}).get(ATTEMPT_HEADER)
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return 0


def exhausted(message: AbstractIncomingMessage) -> bool:
    """True when this job has used up its attempts and belongs in the dead-letter queue."""
    return attempt_of(message) + 1 >= topology.MAX_ATTEMPTS


async def reject(
    message: AbstractIncomingMessage,
    dlx: AbstractExchange,
    *,
    reason: str,
    give_up: bool = False,
) -> None:
    """Send a failed job onward: back for another try, or into the dead-letter queue.

    Republished rather than `nack`-ed, because the attempt counter has to be incremented
    and an incoming message's headers cannot be edited on the way out. The original is
    acked once the copy is safely published — acking first would drop the job if the
    republish failed, and acking never would leave it unacked until the channel closed and
    the broker redelivered it, giving the job an extra attempt nobody counted.

    `give_up` parks the job immediately, for failures where another attempt cannot help: a
    body that will not parse, or a budget that is already spent.

    The caller passes the exchange rather than this module reaching for it through the
    message, so there is exactly one place that declares the topology.
    """
    attempt = attempt_of(message) + 1
    dead = give_up or exhausted(message)
    target = topology.DEAD_QUEUE if dead else topology.RETRY_QUEUE

    headers = dict(message.headers or {})
    headers[ATTEMPT_HEADER] = topology.MAX_ATTEMPTS if dead else attempt
    headers["mycel-error"] = reason[:500]

    await dlx.publish(
        Message(
            body=message.body,
            content_type=message.content_type,
            delivery_mode=DeliveryMode.PERSISTENT,
            headers=headers,
            message_id=message.message_id,
            correlation_id=message.correlation_id,
        ),
        routing_key=target,
    )
    await message.ack()

    log.warning(
        "job failed",
        extra={
            "job_id": message.message_id,
            "attempt": attempt,
            "of": topology.MAX_ATTEMPTS,
            "queue": target,
            "reason": reason,
        },
    )
