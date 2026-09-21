"""One Redis Stream per job, carrying that job's events to whoever is watching.

Reads are non-destructive, so several clients can follow the same job and a client that
reconnects resumes from the last id it saw. The stream is capped and expires: an event is
worth a reload, never a record.
"""

from collections.abc import AsyncGenerator
from typing import Any

from mycel.core.config import get_settings
from mycel.events.event import AgentEvent, SequencedEvent
from mycel.infra.redis.client import get_client

FIRST = "0"


def _key(job_id: str) -> str:
    return f"mycel:events:{job_id}"


def _seq_key(job_id: str) -> str:
    return f"mycel:events:{job_id}:seq"


async def append(job_id: str, event: SequencedEvent) -> None:
    """Add one event and refresh the stream's expiry."""
    settings = get_settings()
    client = await get_client()
    key = _key(job_id)
    await client.xadd(
        key,
        {"json": event.model_dump_json()},
        maxlen=settings.event_stream_max_events,
        approximate=True,
    )
    await client.expire(key, settings.result_ttl_seconds)


async def read(
    job_id: str,
    after: str = FIRST,
    block_ms: int = 5_000,
) -> AsyncGenerator[tuple[str, SequencedEvent] | None]:
    """Yield `(id, event)` from `after` onwards, and `None` each time the wait times out.

    The id is what a client sends back to resume. The `None` matters as much as the events:
    it is the only moment the caller gets control back on a quiet job, and so the only
    chance it has to notice a client that has gone away.
    """
    client = await get_client()
    cursor = after
    while True:
        batch: Any = await client.xread({_key(job_id): cursor}, count=100, block=block_ms)
        if not batch:
            yield None
            continue
        for _, entries in batch:
            for entry_id, fields in entries:
                cursor = entry_id
                yield entry_id, SequencedEvent.model_validate_json(fields["json"])


class RedisEventChannel:
    """An `EventChannel` writing to one job's stream.

    `seq` is a Redis counter, so two workers running the same job still produce one
    sequence rather than two that both start at 1.
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    async def publish(self, event: AgentEvent) -> None:
        client = await get_client()
        seq = await client.incr(_seq_key(self.job_id))
        await client.expire(_seq_key(self.job_id), get_settings().result_ttl_seconds)
        await append(self.job_id, SequencedEvent(seq=seq, **event.model_dump()))
