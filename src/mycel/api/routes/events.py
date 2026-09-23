"""Follow a running job's events over SSE."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from mycel.api.dependencies import current_user
from mycel.core.logging import get_logger
from mycel.infra.redis import streams
from mycel.services.auth import Principal

router = APIRouter(prefix="/chat", tags=["chat"])

log = get_logger(__name__)

#: Sent when a poll finds nothing, so a proxy or a client does not mistake a quiet job for
#: a dead connection.
KEEPALIVE = ": keepalive\n\n"


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

