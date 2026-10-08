"""Structured logs: one JSON line per record on stdout, with `trace_id` and `request_id`."""

import json
import logging
import sys
from contextvars import ContextVar, Token
from typing import Any

from opentelemetry import trace

#: The id of the request being handled, or empty outside one.
current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")

# Anything not in here came from `extra=` and goes in the JSON body.
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

        try:
            ctx = trace.get_current_span().get_span_context()
            if ctx.is_valid:
                payload["trace_id"] = format(ctx.trace_id, "032x")
                payload["span_id"] = format(ctx.span_id, "016x")
        except Exception:  # logging must not raise
            pass

        request_id = current_request_id.get()
        if request_id:
            payload["request_id"] = request_id

        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


#: Libraries that log full request URLs (which may carry credentials) at INFO.
_QUIET = ("httpx", "httpx2", "httpcore")


def setup_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)


def bind_request_id(request_id: str) -> Token[str]:
    """Tag this task's logs with an id; the caller must `reset()` the returned token."""
    return current_request_id.set(request_id)


def get_logger(name: str) -> logging.Logger:
    """A logger for one module. Pass per-record fields with `extra={...}`."""
    return logging.getLogger(name)
