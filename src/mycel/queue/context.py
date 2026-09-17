"""Carry trace context and request_id across the process boundary, so traces do not break
at the queue.

`contextvars` lives inside one process only. A job crossing Kafka into a worker loses all
of it, so it has to be packed and unpacked by hand at both ends:

    producer  inject()  — write trace context into the message headers
    consumer  extract() — restore it before running, making the job's span a child of the
                          request's span

Kept in **headers**, not the payload: headers travel with the message through the retry and
dead-letter topics without anyone touching the job body.

Uses OTel's `TraceContextTextMapPropagator` (W3C traceparent), not an invented format — the
same standard as the HTTP header, so adding another service later still joins up.

Forget either end and nothing reports an error: traces still get written, they just become
two disconnected trees.
"""
