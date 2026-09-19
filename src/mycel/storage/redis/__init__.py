"""Redis: the short-lived things that have to cross a process boundary.

Not a fourth store in the sense the package docstring means. Postgres, Qdrant and the
object store hold records; this holds what is in flight. Everything here carries a TTL and
is expected to vanish — a worker in one process produces it, the API in another reads it,
and after that nobody should be asking.

  results.py   a finished job's report, waiting for the caller that polls for it

It sits under `storage/` rather than `queue/` because `queue/` speaks AMQP and nothing
else: publishing, consuming, retrying, dead-lettering. The result never goes near the
broker — the worker writes it, the API reads it, and the two are connected only by a
`job_id`. Putting it here means the API no longer imports from `queue/` to fetch a report
it never enqueued.
"""
