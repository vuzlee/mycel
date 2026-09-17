"""Background job layer on Kafka: job definitions, retry, dead-letter, idempotency keys.

**Not a broker.** Kafka runs outside, declared in `docker-compose`. This directory is the
layer *on top of* Kafka — swapping brokers means changing things here, and the rest of the
system never notices.

Answers *what runs and what happens on failure*; `scheduler/` answers *when*.

  job.py       a job's shape: payload, idempotency key, retry count, trace context
  producer.py  push a job onto a topic — the entry point is `services/enqueue.py`
  consumer.py  the worker's poll/commit loop
  retry.py     tiered retry topics + dead-letter
  context.py   carry trace context across the process boundary

**Kafka is an ordered log, not a work queue**, so the four things below have to be built by
hand — none is a default, and all four fail silently when done wrong:

1. **Retries cannot be per-message.** Consumers commit by offset, so `seek`-ing back on a
   failed job blocks the whole partition. Instead: push to a retry topic and commit onward —
   see `retry.py`.
2. **Partition count caps parallelism, not worker count.** With 3 partitions a 4th worker
   sits idle. Set partitions to the maximum scale you *expect* from the start: they can be
   increased but not decreased, and increasing them breaks per-key ordering.
3. **Long jobs look dead.** `max.poll.interval.ms` defaults to 5 minutes; generating a
   report takes "a few minutes", squarely in the danger zone — exceeding it triggers a
   rebalance and the job restarts from scratch. Raise this value substantially, or move the
   work off the poll loop.
4. **Commit after finishing, not after receiving.** Commit early and a worker dying mid-job
   loses it. Commit late and a job may run twice — which is why the idempotency key in
   `job.py` is mandatory, not optional.

In exchange, Kafka gives what an ordinary queue does not: the log is retained so it can be
replayed, and another consumer group can read the same stream without affecting existing
workers.
"""
