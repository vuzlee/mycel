"""Retry through a TTL queue, then a dead-letter queue, counted in our own header."""

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage

from mycel.core.logging import get_logger
from mycel.queue import topology

log = get_logger(__name__)

#: Attempt-count header; not `x-` prefixed, which is the broker's namespace.
ATTEMPT_HEADER = "mycel-attempt"


def attempt_of(message: AbstractIncomingMessage) -> int:
    """How many times this job has been tried; absent or malformed means zero."""
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
    """Republish a failed job to retry, or dead-letter it, then ack the original."""
    attempt = attempt_of(message) + 1
    dead = give_up or exhausted(message)
    origin = getattr(message, "routing_key", None) or topology.QUEUE
    target = topology.dead_queue_for(origin) if dead else topology.retry_queue_for(origin)

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
