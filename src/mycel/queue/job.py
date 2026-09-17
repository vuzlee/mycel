"""A job's shape: kind of work, payload, idempotency key, retry count, trace context.

**The idempotency key is mandatory on Kafka**, not optional. Kafka gives at-least-once:
committing after finishing means a worker dying mid-job causes a re-run, and it had *already*
done part of the work. Without a key, one report gets produced twice.

The key should be derived from the work itself (domain + time window + parameters), not a
freshly generated UUID — with a UUID, two calls produce two different keys, which is exactly
what we are trying to avoid.

The Kafka message key serves a different purpose: it picks the partition, and therefore the
ordering. The same data source should land on the same partition so two sync jobs do not
overlap.

Trace context lives in the message headers (see `context.py`), not the payload: headers
travel with the message through the retry and dead-letter topics, so even a failed job can
have its trace reopened to find out why.
"""
