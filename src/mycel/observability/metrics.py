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


def render() -> tuple[bytes, str]:
    """The registry in Prometheus text format, with its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
