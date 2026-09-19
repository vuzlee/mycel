"""Structured logs: one JSON object per line on stdout, always carrying `trace_id`.

Nothing here knows Loki exists. Promtail collects container stdout and ships it; changing
log backend is an edit to `deploy/otel/promtail.yaml`, not to this file.

`trace_id` is the one piece of wiring we do by hand. The logger cannot know it on its own,
so the formatter reads the current OTel span on every record — that is what lets you jump
from a log line straight to its trace instead of hunting by timestamp.

`request_id` works the same way but comes from a contextvar rather than a span, because it
is ours and outlives any one span. `api/middleware.py` sets it; every line logged while
handling that request carries it without a single call site mentioning it. It only follows
the async task, so it does not reach a thread pool or another process — see that module.

If the id is missing, or OTel was never set up, it still logs and never raises. Logging
that kills a request turns a small problem into a large one.
"""

import json
import logging
import sys
from contextvars import ContextVar, Token
from typing import Any

from opentelemetry import trace

#: The id of the request being handled, or empty outside one. Read by the formatter.
current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")

# Attributes LogRecord always carries; anything else was passed via `extra=` and belongs in
# the JSON body.
_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render a record as one JSON line, with trace context attached when there is any."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Never let a missing or broken span stop a log line from being written.
        try:
            ctx = trace.get_current_span().get_span_context()
            if ctx.is_valid:
                payload["trace_id"] = format(ctx.trace_id, "032x")
                payload["span_id"] = format(ctx.span_id, "016x")
        except Exception:  # noqa: BLE001 - logging must not raise
            pass

        request_id = current_request_id.get()
        if request_id:
            payload["request_id"] = request_id

        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def bind_request_id(request_id: str) -> Token[str]:
    """Attach an id to everything logged from here on in this task.

    Returns the token the caller must `current_request_id.reset()` with when the request
    ends — without that the value outlives the request and the next one handled by the
    same task inherits it.
    """
    return current_request_id.set(request_id)


def get_logger(name: str) -> logging.Logger:
    """A logger for one module. Pass per-record fields with `extra={...}`."""
    return logging.getLogger(name)
