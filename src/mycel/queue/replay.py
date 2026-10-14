"""Parked jobs: how many, and putting them back on their work queue."""

from aio_pika import DeliveryMode, Message

from mycel.queue import topology
from mycel.queue.connection import channel
from mycel.queue.retry import ATTEMPT_HEADER

DEAD = {topology.DEAD_QUEUE: topology.QUEUE, topology.INGEST_DEAD_QUEUE: topology.INGEST_QUEUE}


async def depths() -> dict[str, int]:
    """Messages waiting in each dead-letter queue."""
    async with channel() as ch:
        await topology.declare(ch)
        return {
            name: (await ch.declare_queue(name, passive=True)).declaration_result.message_count or 0
            for name in DEAD
        }


async def work_queues() -> dict[str, tuple[int, int]]:
    """Each work queue's waiting messages and its consumer count."""
    async with channel() as ch:
        await topology.declare(ch)
        found: dict[str, tuple[int, int]] = {}
        for name in (topology.QUEUE, topology.INGEST_QUEUE):
            result = (await ch.declare_queue(name, passive=True)).declaration_result
            found[name] = (result.message_count or 0, result.consumer_count or 0)
        return found


async def replay(dead: str, limit: int = 100) -> int:
    """Move up to `limit` jobs from `dead` back to its work queue, attempts reset."""
    moved = 0
    async with channel() as ch:
        topo = await topology.declare(ch)
        queue = await ch.declare_queue(dead, passive=True)
        while moved < limit and (message := await queue.get(fail=False)) is not None:
            headers = {k: v for k, v in (message.headers or {}).items() if k != "mycel-error"}
            headers[ATTEMPT_HEADER] = 0
            await topo.exchange.publish(
                Message(
                    body=message.body,
                    content_type=message.content_type,
                    delivery_mode=DeliveryMode.PERSISTENT,
                    headers=headers,
                    message_id=message.message_id,
                ),
                routing_key=DEAD[dead],
            )
            await message.ack()
            moved += 1
    return moved
