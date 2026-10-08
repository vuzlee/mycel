"""Carry trace context and request_id across the broker in message headers."""

from typing import Any

from opentelemetry import context as otel_context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from mycel.core.logging import current_request_id

#: Carried beside the W3C keys so logs link to the request even with tracing off.
REQUEST_ID_HEADER = "x-mycel-request-id"

_propagator = TraceContextTextMapPropagator()


def inject() -> dict[str, Any]:
    """Headers carrying the caller's trace and request id, as plain strings."""
    headers: dict[str, Any] = {}
    _propagator.inject(headers)
    if request_id := current_request_id.get():
        headers[REQUEST_ID_HEADER] = request_id
    return headers


def extract(headers: dict[str, Any] | None) -> otel_context.Context | None:
    """Bind the request id and return the caller's OTel context for the run to attach."""
    if not headers:
        return None

    if raw := headers.get(REQUEST_ID_HEADER):
        current_request_id.set(str(raw))

    # AMQP header values are the broker's string type; the propagator needs `str`.
    carrier = {str(k): str(v) for k, v in headers.items()}
    ctx = _propagator.extract(carrier)
    return ctx or None
