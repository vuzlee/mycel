"""Exchanges, queues and dead-letter wiring, declared in one place for both sides."""

from dataclasses import dataclass

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue

#: Delay before retry n (1-based) returns a failed job to its work queue.
RETRY_DELAYS_MS = (5_000, 30_000, 120_000)

#: The first try plus one retry per delay; then the dead-letter queue.
MAX_ATTEMPTS = 1 + len(RETRY_DELAYS_MS)

EXCHANGE = "mycel.jobs"
DLX = "mycel.jobs.dlx"

QUEUE = "jobs"
RETRY_QUEUE = "jobs.retry"
DEAD_QUEUE = "jobs.dlq"

#: Document ingest has its own queue so chat jobs never wait behind docling.
INGEST_QUEUE = "ingest"
INGEST_RETRY_QUEUE = "ingest.retry"
INGEST_DEAD_QUEUE = "ingest.dlq"


def retry_queue_for(queue: str, attempt: int = 1) -> str:
    """Where retry `attempt` waits: one queue per delay, so each has a single TTL."""
    base = INGEST_RETRY_QUEUE if queue == INGEST_QUEUE else RETRY_QUEUE
    delay = RETRY_DELAYS_MS[min(max(attempt, 1), len(RETRY_DELAYS_MS)) - 1]
    return f"{base}.{_label(delay)}"


def _label(delay_ms: int) -> str:
    seconds = delay_ms // 1000
    return f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s"


def dead_queue_for(queue: str) -> str:
    return INGEST_DEAD_QUEUE if queue == INGEST_QUEUE else DEAD_QUEUE


@dataclass(frozen=True, slots=True)
class Topology:
    """What both sides need after declaring: where to publish, and what to consume."""

    exchange: AbstractExchange
    dlx: AbstractExchange
    jobs: AbstractQueue
    #: Every delay queue of `jobs`, shortest first.
    retries: tuple[AbstractQueue, ...]
    dead: AbstractQueue
    ingest: AbstractQueue


async def declare(channel: AbstractChannel) -> Topology:
    """Declare everything durably and idempotently, and return the bound objects."""
    exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.DIRECT, durable=True)
    dlx = await channel.declare_exchange(DLX, ExchangeType.DIRECT, durable=True)
    jobs, retries, dead = await _family(channel, exchange, dlx, QUEUE, RETRY_QUEUE, DEAD_QUEUE)
    ingest, _, _ = await _family(
        channel, exchange, dlx, INGEST_QUEUE, INGEST_RETRY_QUEUE, INGEST_DEAD_QUEUE
    )
    return Topology(
        exchange=exchange, dlx=dlx, jobs=jobs, retries=retries, dead=dead, ingest=ingest
    )


async def _family(
    channel: AbstractChannel,
    exchange: AbstractExchange,
    dlx: AbstractExchange,
    name: str,
    retry_name: str,
    dead_name: str,
) -> tuple[AbstractQueue, tuple[AbstractQueue, ...], AbstractQueue]:
    """One work queue, its delay queues, and its dead-letter queue."""
    # No broker-side dead-lettering: `retry.reject` republishes every failure itself.
    work = await channel.declare_queue(name, durable=True)
    await work.bind(exchange, routing_key=name)

    retries = tuple(
        [
            await _delay(channel, dlx, name, f"{retry_name}.{_label(delay)}", delay)
            for delay in RETRY_DELAYS_MS
        ]
    )

    dead = await channel.declare_queue(dead_name, durable=True)
    await dead.bind(dlx, routing_key=dead_name)
    return work, retries, dead


async def _delay(
    channel: AbstractChannel, dlx: AbstractExchange, work: str, name: str, delay_ms: int
) -> AbstractQueue:
    """A queue nobody consumes: each message waits `delay_ms`, then dead-letters to `work`."""
    queue = await channel.declare_queue(
        name,
        durable=True,
        arguments={
            "x-message-ttl": delay_ms,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": work,
        },
    )
    await queue.bind(dlx, routing_key=name)
    return queue
