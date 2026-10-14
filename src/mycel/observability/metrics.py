"""Prometheus metrics.

Labels must be low-cardinality (agent, model, status, layer, domain), never ids:
each label combination is a series held in memory forever.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

sync_duration_seconds = Histogram(
    "mycel_sync_duration_seconds",
    "Wall time of one sync run, from first fetch to the last row written.",
    ["domain"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600),
)

records_written = Gauge(
    "mycel_records_written",
    "Rows written by the most recent sync at one layer.",
    ["domain", "layer"],
)

tokens_spent_total = Counter(
    "mycel_tokens_spent_total",
    "Model tokens consumed, since this process started.",
    ["model", "direction"],
)

jobs_total = Counter(
    "mycel_jobs_total",
    "Queued jobs that reached a terminal state.",
    ["kind", "status"],
)

job_attempts = Histogram(
    "mycel_job_attempt_seconds",
    "Wall time of one attempt at a job, by kind and how it ended.",
    ["kind", "outcome"],
    buckets=(0.5, 1, 5, 15, 30, 60, 120, 300, 600),
)

queue_ready = Gauge(
    "mycel_queue_ready",
    "Jobs waiting in a work queue, not yet handed to a worker.",
    ["queue"],
)

queue_consumers = Gauge(
    "mycel_queue_consumers",
    "Workers consuming a work queue; zero with jobs waiting means nothing runs them.",
    ["queue"],
)


dead_letters = Gauge(
    "mycel_dead_letters",
    "Jobs parked in a dead-letter queue; anything above zero needs a look.",
    ["queue"],
)


redis_memory_ratio = Gauge(
    "mycel_redis_memory_ratio",
    "The state Redis's used memory over its maxmemory; it refuses writes at 1.",
)


def start_job_series(kinds: list[str]) -> None:
    """Every kind and outcome at zero: `increase()` misses a series' first sample, so a counter
    that appears at 4 reads as no failures at all."""
    for kind in kinds:
        for outcome in ("done", "retried", "failed"):
            job_attempts.labels(kind=kind, outcome=outcome)


def render() -> tuple[bytes, str]:
    """The registry in Prometheus text format, with its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
