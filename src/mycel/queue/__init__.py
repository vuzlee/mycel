"""Background job layer on RabbitMQ: job definitions, retry, dead-letter, idempotency keys.

**Not a broker.** RabbitMQ runs outside, declared in `docker-compose`. This directory is the
layer *on top of* it — swapping brokers means changing things here, and the rest of the
system never notices.

Answers *what runs and what happens on failure*; `scheduler/` answers *when*.

  job.py       a job's shape: payload, idempotency key, retry count, trace context
  producer.py  publish a job to an exchange — the entry point is `services/enqueue.py`
  consumer.py  the worker's consume/ack loop
  retry.py     dead-letter exchange with a TTL, and a final dead-letter queue
  context.py   carry trace context across the process boundary

**Why RabbitMQ and not Kafka.** A few reports an hour do not need a partitioned log, a JVM
or replay. What they need is one consumer per message, redelivery when a worker dies, and a
dead-letter queue — which is what a broker gives directly. Kafka would mean building all
three by hand: retry topics instead of a DLX, a retry counter in the headers because offsets
do not count attempts, and a raised `max.poll.interval.ms` because a long job looks dead to
a consumer group. See the comment in `docker-compose.yml`.

Four things still have to be got right, and each fails quietly when it is not:

1. **Ack after finishing, not on delivery.** `auto_ack` loses a job the moment a worker dies
   mid-report. Manual ack after the work completes gives at-least-once — which is why the
   idempotency key in `job.py` is mandatory, not optional.
2. **Bound the prefetch.** Without `basic_qos(prefetch_count=...)` one worker takes every
   queued message and the rest idle. One or two in flight per worker is right for jobs that
   run for minutes.
3. **A failed job must not be requeued in a loop.** `nack(requeue=True)` puts it straight
   back at the head and it fails again immediately. Reject it to the dead-letter exchange
   instead — see `retry.py`.
4. **Long jobs must outlive the timeouts.** RabbitMQ has no consumer-side poll deadline, but
   an unacked delivery does age against `consumer_timeout` (30 minutes by default). A report
   that can run longer than that needs the value raised on the broker.

Parallelism is the number of consumers, not a partition count fixed up front: workers can be
added and removed freely, which is the practical difference from the Kafka design.
"""
