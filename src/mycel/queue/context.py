"""Carry trace context and request_id across the process boundary, so traces do not break
at the queue.

`contextvars` lives inside one process only. A job crossing the broker into a worker loses
all of it, so it has to be packed and unpacked by hand at both ends:

    producer  inject()  — write trace context into the message headers
    consumer  extract() — restore it before running, making the job's span a child of the
                          request's span

Kept in **headers**, not the payload: headers survive the trip through the dead-letter
exchange and the retry queues without anyone touching the job body.

Uses OTel's `TraceContextTextMapPropagator` (W3C traceparent), not an invented format — the
same standard as the HTTP header, so adding another service later still joins up.

Forget either end and nothing reports an error: traces still get written, they just become
two disconnected trees.
"""

from typing import Any

from opentelemetry import context as otel_context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from mycel.core.logging import current_request_id

#: Carried beside the W3C keys because it is ours, not OTel's: the request id ties a job's
#: log lines back to the HTTP request that created it even when tracing is switched off.
REQUEST_ID_HEADER = "x-mycel-request-id"

_propagator = TraceContextTextMapPropagator()


def inject() -> dict[str, Any]:
    """Headers to publish alongside a job, capturing the caller's trace and request id.

    Returns plain strings only: AMQP headers are a typed table, and a value the encoder
    does not recognise fails at publish time rather than here.
    """
    headers: dict[str, Any] = {}
    _propagator.inject(headers)
    if request_id := current_request_id.get():
        headers[REQUEST_ID_HEADER] = request_id
    return headers


def extract(headers: dict[str, Any] | None) -> otel_context.Context | None:
    """Restore the caller's context from a message's headers, before the job runs.

    Binds the request id as a side effect — it is a `contextvar`, so binding it here covers
    every log line the job produces. The returned OTel context is for the caller to attach
    around the run; returning it rather than attaching it here keeps the detach in the same
    scope as the attach.

    A message with no trace headers is normal, not an error: anything published outside a
    request (a CLI, a retry from an old deployment) simply starts its own trace.
    """
    if not headers:
        return None

    if raw := headers.get(REQUEST_ID_HEADER):
        current_request_id.set(str(raw))

    # AMQP hands back the broker's own string type for header values, which the propagator
    # reads as a plain string only after `str()`.
    carrier = {str(k): str(v) for k, v in headers.items()}
    ctx = _propagator.extract(carrier)
    return ctx or None
