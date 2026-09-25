"""Follow a running job's events over SSE."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from mycel.api.dependencies import current_user
from mycel.core.logging import get_logger
from mycel.domains.chat import find_turn
from mycel.events.event import RUN_FINISHED, SequencedEvent
from mycel.infra.redis import streams
from mycel.services.auth import Principal

router = APIRouter(prefix="/chat", tags=["chat"])

log = get_logger(__name__)

#: Sent when a poll finds nothing, so a proxy or a client does not mistake a quiet job for
#: a dead connection.
KEEPALIVE = ": keepalive\n\n"

#: The turn statuses that mean the run is over and will emit nothing more. `queued` is
#: deliberately not among them: it is written before the worker ever sees the job.
FINISHED = frozenset({"done", "failed"})


@router.get("/{job_id}/events")
async def stream_events(
    request: Request,
    job_id: str,
    user: Annotated[Principal, Depends(current_user)],
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Stream the job's events, resuming after `Last-Event-ID` when the client reconnects."""
    return StreamingResponse(
        _frames(request, job_id, last_event_id or streams.FIRST),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _frames(request: Request, job_id: str, after: str) -> AsyncIterator[str]:
    """Yield SSE frames until the client goes away.

    The `id:` line is the Redis stream id, which is what the browser sends back as
    `Last-Event-ID` — so a reconnect resumes rather than replaying from the start.

    No `event:` line: the type lives in the JSON instead. With one, a client must register
    a listener per type and silently drops any type it was not built for, which is the
    opposite of what the envelope's `type` field is for.
    """
    # A run whose stream is gone has no events left to wait for. Redis keeps the stream
    # under a TTL and loses it outright on restart, while `app.turn` keeps the answer — so
    # without this the client subscribes to a key that will never receive anything, `xread`
    # blocks until it times out, and the composer stays disabled on a question that was
    # answered days ago.
    #
    # Both questions, not just the record. A run that finished a second ago also has a turn
    # row, and its stream is still there holding every tool call it made — closing on the
    # record alone would swallow the whole activity list of every run the reader watches.
    #
    # And the row has to be a FINISHED one. A turn is written twice, and the first write is
    # `queued`, at the moment the question is enqueued — so a run that has not started yet
    # answers both of the questions above: its stream does not exist, because the key is
    # created by the first `xadd` and the worker is still a broker hop away, and its row is
    # already there. The page opens this stream immediately after POST /chat, which put it
    # squarely in that window: it was told the run had finished before the run began, shut
    # the EventSource, and every event the run went on to produce arrived in a Redis stream
    # nobody was reading. On screen that is a question stuck on "Working through it" while
    # the composer frees up — the answer is in the poll, and the whole activity list is
    # lost.
    #
    # Only when the client is asking from the start. A reconnect carrying `Last-Event-ID`
    # is resuming a live run, and its remaining events are in the stream.
    kept = await find_turn(job_id) if after == streams.FIRST else None
    if (
        after == streams.FIRST
        and not await streams.exists(job_id)
        and kept is not None
        and kept.status in FINISHED
    ):
        done = SequencedEvent(agent="system", type=RUN_FINISHED, seq=0)
        yield f"data: {done.model_dump_json()}\n\n"
        return

    events = streams.read(job_id, after=after)
    try:
        async for item in events:
            if await request.is_disconnected():
                break
            if item is None:
                yield KEEPALIVE
                continue
            event_id, event = item
            yield f"id: {event_id}\ndata: {event.model_dump_json()}\n\n"
    finally:
        # The generator holds a blocking `xread`. Without this it is only collected when
        # the loop next gets round to it, and the connection count climbs.
        await events.aclose()
        log.debug("event stream closed", extra={"job_id": job_id})
