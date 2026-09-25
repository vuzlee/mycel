"""Prometheus metrics: sync latency, record counts per layer, tokens spent, job failure rate.

Metrics answer "is something broken", traces answer "where". Both are needed.

**Four metrics, and adding a fifth is a decision.** Each one here exists because a
question was asked that nothing could answer: is the data fresh, did a layer lose rows,
what is this costing, are jobs dying. A metric nobody reads is a series that costs RAM
forever, so a new one arrives with the question it answers.

**LABEL RULE — the one thing that must not be got wrong.**

    allowed      agent, model, status, layer, domain
    never        job_id, thread_id, user_id, issue_key, or any other identifier

Prometheus holds one time series per distinct combination of label values, in memory, for
as long as the server runs. A counter labelled by `agent` x `model` x `status` is a few
dozen series and stays a few dozen forever. A counter labelled by `job_id` mints a new
series per job and none of them ever dies.

It fails slowly, which is why the rule is written here rather than in a note: on day one
nothing looks wrong, and the person adding the fifth metric reads this file. `tests/
test_metrics.py` also asserts it, so a label that is an id turns a test red.

**One registry per process, and it is the default one.** `prometheus_client` keeps a
global `REGISTRY`, and the collector objects below register themselves into it at import.
That makes importing this module twice an error rather than a silent double count — which
is the behaviour we want, and why nothing here builds a metric lazily inside a function.

Exposed over HTTP by `observability/metrics_server.py` in the worker and the scheduler,
and by a route in the api, which already has a port.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

#: How long a full sync took, by domain. A histogram rather than a gauge because the
#: question is "is it getting slower", which needs the distribution, not the last value.
sync_duration_seconds = Histogram(
    "mycel_sync_duration_seconds",
    "Wall time of one sync run, from first fetch to the last row written.",
    ["domain"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600),
)

#: Rows written at each layer on the last sync. A gauge: the question is "did silver get
#: fewer rows than bronze", which is about the current state, not a rate.
records_written = Gauge(
    "mycel_records_written",
    "Rows written by the most recent sync at one layer.",
    ["domain", "layer"],
)

#: Tokens are the bill. Split by direction because input and output are priced apart, and
#: by model because that is the other half of the multiplication.
tokens_spent_total = Counter(
    "mycel_tokens_spent_total",
    "Model tokens consumed, since this process started.",
    ["model", "direction"],
)

#: Jobs by how they ended. A failure rate is this counter divided by itself, which is why
#: it is one counter with a `status` label rather than two counters.
jobs_total = Counter(
    "mycel_jobs_total",
    "Queued jobs that reached a terminal state.",
    ["kind", "status"],
)


def render() -> tuple[bytes, str]:
    """The registry as Prometheus' text format, with the content type it must be served as.

    Returned rather than written to a response, because the three processes that expose it
    have three different HTTP layers and only this part is shared.
    """
    return generate_latest(), CONTENT_TYPE_LATEST
