"""Follow a running job's events over SSE."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from mycel.api.dependencies import CurrentUser
from mycel.core.logging import get_logger
from mycel.domains.chat import find_turn
from mycel.events.event import RUN_FINISHED, SequencedEvent
from mycel.infra.redis import streams

router = APIRouter(prefix="/chat", tags=["chat"])

log = get_logger(__name__)

#: Sent when a poll finds nothing, so a quiet job is not mistaken for a dead one.
KEEPALIVE = ": keepalive\n\n"

#: The turn statuses that mean the run is over and will emit nothing more.
FINISHED = frozenset({"done", "failed"})


@router.get("/{job_id}/events")
async def stream_events(
    request: Request,
    job_id: str,
    user: CurrentUser,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Stream the job's events, resuming after `Last-Event-ID` when the client reconnects."""
    return StreamingResponse(
        _frames(request, job_id, last_event_id or streams.FIRST),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _frames(request: Request, job_id: str, after: str) -> AsyncIterator[str]:
    """Yield SSE frames until the client goes away."""
    # A run whose stream is gone has no events left to wait for.
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
        # The generator holds a blocking `xread`.
        await events.aclose()
        log.debug("event stream closed", extra={"job_id": job_id})
