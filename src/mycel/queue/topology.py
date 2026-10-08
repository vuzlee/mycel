"""Exchanges, queues and dead-letter wiring, declared in one place for both sides."""

from dataclasses import dataclass

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue

#: Delay before a failed job returns to its work queue.
RETRY_DELAY_MS = 60_000

#: Retries before a job is parked in the dead-letter queue.
MAX_ATTEMPTS = 3

EXCHANGE = "mycel.jobs"
DLX = "mycel.jobs.dlx"

QUEUE = "jobs"
RETRY_QUEUE = "jobs.retry"
DEAD_QUEUE = "jobs.dlq"

#: Document ingest has its own queue so chat jobs never wait behind docling.
INGEST_QUEUE = "ingest"
INGEST_RETRY_QUEUE = "ingest.retry"
INGEST_DEAD_QUEUE = "ingest.dlq"


def retry_queue_for(queue: str) -> str:
    return INGEST_RETRY_QUEUE if queue == INGEST_QUEUE else RETRY_QUEUE


def dead_queue_for(queue: str) -> str:
    return INGEST_DEAD_QUEUE if queue == INGEST_QUEUE else DEAD_QUEUE


@dataclass(frozen=True, slots=True)
class Topology:
    """What both sides need after declaring: where to publish, and what to consume."""

    exchange: AbstractExchange
    dlx: AbstractExchange
    jobs: AbstractQueue
    retry: AbstractQueue
    dead: AbstractQueue
    ingest: AbstractQueue


async def declare(channel: AbstractChannel) -> Topology:
    """Declare everything durably and idempotently, and return the bound objects."""
    exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.DIRECT, durable=True)
    dlx = await channel.declare_exchange(DLX, ExchangeType.DIRECT, durable=True)
    jobs, retry, dead = await _family(channel, exchange, dlx, QUEUE, RETRY_QUEUE, DEAD_QUEUE)
    ingest, _, _ = await _family(
        channel, exchange, dlx, INGEST_QUEUE, INGEST_RETRY_QUEUE, INGEST_DEAD_QUEUE
    )
    return Topology(exchange=exchange, dlx=dlx, jobs=jobs, retry=retry, dead=dead, ingest=ingest)


async def _family(
    channel: AbstractChannel,
    exchange: AbstractExchange,
    dlx: AbstractExchange,
    name: str,
    retry_name: str,
    dead_name: str,
) -> tuple[AbstractQueue, AbstractQueue, AbstractQueue]:
    """One work queue, its delayed-retry queue, and its dead-letter queue."""
    work = await channel.declare_queue(
        name,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX, "x-dead-letter-routing-key": retry_name},
    )
    await work.bind(exchange, routing_key=name)

    retry = await channel.declare_queue(
        retry_name,
        durable=True,
        arguments={
            "x-message-ttl": RETRY_DELAY_MS,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": name,
        },
    )
    await retry.bind(dlx, routing_key=retry_name)

    dead = await channel.declare_queue(dead_name, durable=True)
    await dead.bind(dlx, routing_key=dead_name)
    return work, retry, dead
