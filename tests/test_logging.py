"""The JSON formatter: valid line out every time, trace context when there is a span,
and never an exception that takes the caller down with it."""

import json
import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from mycel.core.logging import JsonFormatter


def _format(record: logging.LogRecord) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(JsonFormatter().format(record))
    return out


def _record(msg: str = "hello", **extra: Any) -> logging.LogRecord:
    rec = logging.LogRecord("mycel.test", logging.INFO, "f.py", 1, msg, None, None)
    rec.__dict__.update(extra)
    return rec


def test_emits_one_json_object() -> None:
    out = _format(_record())
    assert out["message"] == "hello"
    assert out["level"] == "INFO"
    assert out["logger"] == "mycel.test"


def test_extra_fields_reach_the_body() -> None:
    """job_id and request_id are passed via extra= and must survive into the line."""
    out = _format(_record(job_id="job-1", request_id="req-2"))
    assert out["job_id"] == "job-1"
    assert out["request_id"] == "req-2"


def test_no_span_still_logs() -> None:
    """Without OTel set up there is no trace id, and that must not be an error."""
    out = _format(_record())
    assert "trace_id" not in out
    assert out["message"] == "hello"


def test_trace_id_attached_inside_a_span() -> None:
    """The whole point: a log line must carry the id that joins it to its trace."""
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("unit") as span:
        out = _format(_record())
        expected = format(span.get_span_context().trace_id, "032x")
    assert out["trace_id"] == expected
    assert len(out["trace_id"]) == 32


def test_unserialisable_extra_does_not_raise() -> None:
    """Logging is not allowed to turn a small problem into a large one."""
    out = _format(_record(obj=object()))
    assert "obj" in out
