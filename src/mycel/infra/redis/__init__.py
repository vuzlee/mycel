"""Redis: the short-lived things that have to cross a process boundary.

Not a fourth store in the sense the package docstring means. Postgres, Qdrant and the
object store hold records; this holds what is in flight. Everything here carries a TTL and
is expected to vanish — a worker in one process produces it, the API in another reads it,
and after that nobody should be asking.

  client.py    the connections, and why there are two of them
  results.py   a finished job's answer, waiting for the caller that polls for it
  budgets.py   what a job has spent, so its ceiling survives a retry or a second worker
  streams.py   one stream per job, carrying its events to whoever is watching
  drafts.py    an event the model proposed, until the person either agrees or forgets
  answers.py   cached Knowledge answers, keyed by documents, prompt and models
  citations.py the sources of a finished answer, beside it in `results`
  document_events.py  a nudge to the page when a user's documents change

It sits under `infra/` rather than `queue/` because `queue/` speaks AMQP and nothing else:
publishing, consuming, retrying, dead-lettering. Nothing here goes near the broker — the
worker writes, the API reads, and the two are connected only by a `job_id`. Putting it here
means the API no longer imports from `queue/` to fetch an answer it never enqueued.
"""
