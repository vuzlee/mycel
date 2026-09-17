"""Push one job onto the queue and return its job_id.

Wraps `queue/` into a single call: the pipeline need not know what the queue runs on.
Every job carries an idempotency key, so calling twice does not produce two duplicate
reports.
"""
