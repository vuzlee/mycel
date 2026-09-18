"""A job's shape: kind of work, payload, idempotency key, retry count, trace context.

**The idempotency key is mandatory**, not optional. Acking after the work finishes gives
at-least-once: a worker dying mid-job means the broker redelivers it, and it had *already*
done part of the work. Without a key, one report gets produced twice.

The key should be derived from the work itself (domain + time window + parameters), not a
freshly generated UUID — with a UUID, two calls produce two different keys, which is exactly
what we are trying to avoid.

The routing key serves a different purpose: it picks the queue, and therefore which pool of
workers takes the job. Slow bulk syncs and interactive report jobs belong on separate
queues so one cannot starve the other.

Trace context lives in the message headers (see `context.py`), not the payload: headers
survive the trip through the dead-letter exchange, so even a failed job can have its trace
reopened to find out why.
"""
