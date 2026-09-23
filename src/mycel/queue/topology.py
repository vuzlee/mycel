"""Exchange, queues and dead-letter wiring, declared in one place.

**Both sides call this, and neither declares anything of its own.** A producer and a
consumer that declare the same queue with different arguments is the classic silent
RabbitMQ failure: whichever runs second gets `PRECONDITION_FAILED` and, on a channel that
nobody is watching, the process simply stops receiving. Declaring from one function means
there is only one set of arguments to disagree with.

The shape:

    mycel.jobs (direct exchange)
      └─ jobs                  x-dead-letter-exchange: mycel.jobs.dlx
    mycel.jobs.dlx (direct)
      ├─ jobs.retry            x-message-ttl, dead-letters back to mycel.jobs
      └─ jobs.dlq              nothing consumes it; kept for inspection

Nothing consumes `jobs.retry`. A rejected message lands there, ages out against the
queue's TTL, and the broker routes it back to `jobs` by itself — the delay is the TTL, not
a consumer sleeping. `retry.py` decides which of the two dead-letter queues a failure goes
to.

Declarations are idempotent, so calling this on every connection is correct and cheap. It
also means a cold `docker compose up` needs no setup step: whichever process starts first
creates the topology.
"""

from dataclasses import dataclass

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue

#: Retry delay before a failed job is handed back to `jobs`. One value, not a tiered chain:
#: the failures worth retrying here are a provider 503 or a rate limit, and both clear in
#: about this long. Tiers can be added by declaring more retry queues with longer TTLs.
RETRY_DELAY_MS = 60_000

#: How many times a job is retried before it is parked in the dead-letter queue. Counted in
#: a header we write, not from the broker's own `x-death` array, which is easier to read
#: wrong than to read.
MAX_ATTEMPTS = 3

EXCHANGE = "mycel.jobs"
DLX = "mycel.jobs.dlx"

QUEUE = "jobs"
RETRY_QUEUE = "jobs.retry"
DEAD_QUEUE = "jobs.dlq"


@dataclass(frozen=True, slots=True)
class Topology:
    """What both sides need after declaring: where to publish, and what to consume."""

    exchange: AbstractExchange
    dlx: AbstractExchange
    jobs: AbstractQueue
    retry: AbstractQueue
    dead: AbstractQueue


async def declare(channel: AbstractChannel) -> Topology:
    """Declare everything, idempotently, and hand back the bound objects.

    Durable throughout: a broker restart with transient queues loses every queued job, and
    a job nobody knows was dropped is worse than one that fails loudly.
    """
    exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.DIRECT, durable=True)
    dlx = await channel.declare_exchange(DLX, ExchangeType.DIRECT, durable=True)

    jobs = await channel.declare_queue(
        QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX, "x-dead-letter-routing-key": RETRY_QUEUE},
    )
    await jobs.bind(exchange, routing_key=QUEUE)

    # Dead-letters back to the main exchange once the TTL expires. Without the routing key
    # override the message would keep its original one and loop straight back here.
    retry = await channel.declare_queue(
        RETRY_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": RETRY_DELAY_MS,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": QUEUE,
        },
    )
    await retry.bind(dlx, routing_key=RETRY_QUEUE)

    # The end of the line: no TTL and no dead-letter target, so a message stays until
    # somebody looks at it.
    dead = await channel.declare_queue(DEAD_QUEUE, durable=True)
    await dead.bind(dlx, routing_key=DEAD_QUEUE)

    return Topology(exchange=exchange, dlx=dlx, jobs=jobs, retry=retry, dead=dead)
