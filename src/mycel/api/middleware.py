"""Hand-written middleware: a `request_id`, its timing in Prometheus, and a cap on load."""

import json
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mycel.core.logging import bind_request_id, current_request_id
from mycel.observability.metrics import http_requests

#: The header a request id arrives in and leaves in.
HEADER = "x-request-id"


class RequestIdMiddleware:
    """Give every request an id, put it where the logger finds it, send it back."""

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
                # Replace rather than append.
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
            # Reset even on failure, or the contextvar leaks into the next request.
            current_request_id.reset(token)


def _incoming(scope: Scope) -> str | None:
    """The id an upstream proxy already assigned, if there is one."""
    for key, value in scope.get("headers", []):
        if key.decode().lower() == HEADER:
            return value.decode()[:200] or None
    return None


#: The label for a path no route matched, so scanners cannot mint one series per URL.
UNMATCHED = "unmatched"


class MetricsMiddleware:
    """Time every request into `mycel_http_request_seconds`, labelled by route template."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = 500  # what the client gets if the app raises before answering
        started = time.perf_counter()

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            http_requests.labels(
                method=scope["method"], route=_route(scope), status=str(status)
            ).observe(time.perf_counter() - started)


def _route(scope: Scope) -> str:
    """`/chat/{job_id}`, not `/chat/abc123`; a mount such as `/app` counts as one route."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else UNMATCHED


#: Long-lived streams and probes: they wait, not work, so they never count against the cap.
UNCAPPED = ("/health", "/app")


class InFlightLimit:
    """Answer 503 at once past `limit` requests in flight, before they queue to a timeout."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit
        self.in_flight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _uncapped(scope["path"]):
            await self.app(scope, receive, send)
            return
        if self.in_flight >= self.limit:
            await _overloaded(send)
            return
        self.in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_flight -= 1


def _uncapped(path: str) -> bool:
    return path.startswith(UNCAPPED) or path.endswith(("/events", "/documents/status"))


async def _overloaded(send: Send) -> None:
    body = json.dumps(
        {
            "error": "overloaded",
            "detail": "too many requests at once; try again shortly",
            "request_id": current_request_id.get() or None,
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", b"1"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
