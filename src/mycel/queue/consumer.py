"""The worker's consume loop: receive a job, run it, ack.

Three settings have to be got right here, and all three fail silently:

  auto_ack=False        auto-ack acks on delivery, before the job finishes -> a worker dying
                        mid-job loses it
  ack after finishing   the order is: run, then ack. Not the reverse
  prefetch_count        set it low (1-2). Unbounded, one worker takes every queued message
                        and the others idle while it works through them one at a time

A failed job is **not** `nack`-ed with `requeue=True` — that returns it to the head of the
queue and it fails again immediately, spinning. Reject it without requeue so the dead-letter
exchange takes it; see `retry.py`.

Jobs that run for a long time age against the broker's `consumer_timeout` (30 minutes by
default) while unacked. Exceed it and the channel is closed and the job is redelivered, so
raise the value on the broker for anything that can run longer.

Call `context.extract()` on receipt, before running, so the job's span attaches to the span
of the request that created it.
"""
