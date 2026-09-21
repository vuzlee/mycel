"""Hand-written middleware — exactly one: attach a `request_id` to every request.

Everything else is **not** hand-written, because it already exists and rewriting it
means maintaining a re-implementation of something already standardised:

  tracing      `FastAPIInstrumentor.instrument_app(app)` — follows OTel semantic
               conventions (`http.route`, `http.status_code`); a hand-rolled one drifts
  CORS         Starlette's `CORSMiddleware`
  errors       `@app.exception_handler(...)` — FastAPI's own mechanism, not middleware
  rate limit   Nginx/ingress blocks before reaching the app; use `slowapi` for per-user
  auth         `Depends()` — see `dependencies.py`, which explains why it is not here

Why `request_id` still has to be hand-written: the value is in putting the id into
`contextvars` so `observability/logging.py` picks it up on its own, which keeps
routes from writing `log.info(..., request_id=rid)` on every line. The logger is
ours, so no library can wire that up for us; given that, writing it directly beats
adding a dependency.

Reuse the id from the header when present (preserving the chain across services),
otherwise generate one. Return it in the response header so whoever reports a problem
has the exact id to look up.

**Write it as pure ASGI, not `BaseHTTPMiddleware`.** That one buffers the response and
so stalls SSE, and agent output is meant to reach the client as it is produced. This
failure is silent: tokens just arrive as one lump at the end.

**`contextvars` (Python built-in, not a FastAPI feature) follows the async task only.**
Boundaries it does not cross:

    await                   preserved — same task
    create_task()           child copies the context at creation; a child's set is
                            invisible to the parent
    run_in_executor/thread  NOT carried over, must be passed explicitly
    another process         gone entirely — see `queue/__init__.py`

That last line is the one we actually hit: jobs run in a separate worker process, so the
id does not travel with them.
"""

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mycel.core.logging import bind_request_id, current_request_id

#: The header a request id arrives in and leaves in. `X-Request-ID` is the de facto name;
#: matching it means an id set by a proxy upstream is picked up rather than replaced.
HEADER = "x-request-id"


class RequestIdMiddleware:
    """Give every request an id, put it where the logger finds it, send it back.

    Pure ASGI rather than `BaseHTTPMiddleware`, for the reason in this module's docstring:
    that one buffers the response body, which would stall the SSE stream that batch 005
    adds. Getting this wrong fails silently — tokens simply arrive in one lump at the end —
    so it is written the safe way now, while there is nothing to break.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Lifespan and websocket messages have no headers to read or write.
            await self.app(scope, receive, send)
            return

        request_id = _incoming(scope) or uuid.uuid4().hex
        token = bind_request_id(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Replace rather than append. Appending gives two values for one header
                # when anything further in has already set it — which readers join with a
                # comma, so the id silently becomes `abc, abc` and no longer matches the
                # one in the logs.
                kept = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.decode().lower() != HEADER
                ]
                kept.append((HEADER.encode(), request_id.encode()))
                message["headers"] = kept
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # Reset even on failure: the contextvar outlives the request otherwise, and
            # the next one handled by this task would log somebody else's id.
            current_request_id.reset(token)


def _incoming(scope: Scope) -> str | None:
    """The id an upstream proxy already assigned, if there is one.

    Reusing it keeps one chain of ids across services; generating a fresh one here would
    break the link at exactly the boundary where a reader needs it.
    """
    for key, value in scope.get("headers", []):
        if key.decode().lower() == HEADER:
            return value.decode()[:200] or None
    return None
