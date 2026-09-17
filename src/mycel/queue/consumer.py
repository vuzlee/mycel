"""The worker's poll loop: receive a job, run it, commit.

Three Kafka constraints have to be respected here, and all three fail silently:

  enable_auto_commit=False   auto-commit commits before the job finishes -> dying mid-job
                             loses it
  commit after finishing     the order is: run, then commit. Not the reverse
  max_poll_interval_ms       raise it well above the 5-minute default, since generating a
                             report takes minutes. Exceed it and Kafka considers this
                             worker dead, rebalances, and the job runs again

A failed job is **not** seek-ed back — that blocks the whole partition. Push it to a retry
topic and commit onward; see `retry.py`.

Call `context.extract()` on receipt, before running, so the job's span attaches to the span
of the request that created it.
"""
