"""Tiered retry and dead-letter, built from a dead-letter exchange and a message TTL.

Do not `nack(requeue=True)`: the message goes back to the head of the queue and fails again
at once, burning a worker in a tight loop. Reject it without requeue instead, and let the
queue's `x-dead-letter-exchange` move it on:

    jobs            first attempt; dead-letters to ->
    jobs.retry.1m   x-message-ttl 60s, dead-letters back to `jobs` when it expires
    jobs.retry.10m  same, longer
    jobs.dlq        out of attempts — kept for inspection, not silently dropped

The delay is the queue's TTL, not a consumer sleeping: nothing consumes the retry queues at
all. A message sits there until it expires and the broker routes it onward by itself.

The attempt count is tracked in the message headers. The broker's own `x-death` header also
counts rejections per queue, but it is easier to read a counter we wrote than to sum that
array.

Trace context travels in the headers across all four queues, so a job that lands in
`jobs.dlq` can still have its trace reopened from the moment the user pressed the button.
"""
